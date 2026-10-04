"""Fit every decision threshold on the validation split and evaluate the full decision logic on test.

Produces the Calibration JSON the app loads. Everything is fitted on hemlock
VAL trees (identity-disjoint from train and test) and then applied unchanged
to TEST trees, through the same ``fusion.decide`` function the app uses.

Usage:
    python scripts/calibrate.py --emb runs/reid/X/embeddings.npy --species runs/species/X/species_results.json \
        --out runs/export/calibration.json --report runs/results/decision_X.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from hemlock_sentinel.evaluation.benchmarks import build_observations, run_open_set
from hemlock_sentinel.evaluation.metrics import open_set_metrics
from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.evaluation.benchmarks import all_pairs, decide_global
from hemlock_sentinel.reid.calibration import (Calibration, LogisticCalibrator, threshold_at_fmr,
                                               threshold_for_gallery)
from hemlock_sentinel.reid.fusion import candidate_features, decide

FEATS = ["global", "gap", "agreement"]


def candidate_rows(qs, k):
    X, y, qid = [], [], []
    for n, q in enumerate(qs):
        for j in np.argsort(-q.scores)[:k]:
            f = candidate_features(q.scores, q.view_scores, q.tree_ids, q.tree_ids[j])
            X.append([f[c] for c in FEATS])
            y.append(int(q.truth == q.tree_ids[j]))
            qid.append(n)
    return np.array(X), np.array(y), np.array(qid)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb", required=True)
    ap.add_argument("--species", required=True)
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--target-fmr", type=float, default=0.01)
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--duplicate", default=None, help="runs/results/duplicate.json from calibrate_duplicate.py")
    ap.add_argument("--calib-species", default="hemlock", choices=["hemlock", "all"],
                    help="all: pool within-species open-set trials of every species' VAL trees "
                         "(more impostor data than 9 val hemlocks); test is always hemlock")
    args = ap.parse_args()
    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    emb = np.load(args.emb)
    emb_of = {r.path: emb[i] for i, r in enumerate(recs)}
    sp = json.loads(Path(args.species).read_text())

    if args.calib_species == "hemlock":
        qv = run_open_set(build_observations(recs, set(splits["val"]), "tsuga_canadensis", 3, 1), emb_of,
                          repeats=args.repeats, seed=100)
    else:
        qv = []
        for sp_name in sorted({r.species for r in recs if r.tree_id in set(splits["val"])}):
            ob = build_observations(recs, set(splits["val"]), sp_name, 3, 1)
            if len({o.tree_id for o in ob}) >= 4:
                qv += run_open_set(ob, emb_of, repeats=args.repeats, seed=100)
    qt = run_open_set(build_observations(recs, set(splits["test"]), "tsuga_canadensis", 3, 2), emb_of,
                      repeats=args.repeats, seed=200)

    # 1. global-only threshold (fallback)
    imp = [np.delete(q.scores, q.tree_ids.index(q.truth)).max() if q.truth else q.scores.max() for q in qv]
    t_global = threshold_at_fmr(np.array(imp), args.target_fmr)
    # 2. logistic fuser on candidate pairs
    Xv, yv, qidv = candidate_rows(qv, args.k)
    fuser = LogisticCalibrator(FEATS).fit(Xv, yv)
    pv = fuser.predict_proba(Xv)
    best_wrong = np.full(len(qv), 0.0)
    for p, y, n in zip(pv, yv, qidv):
        if not y:
            best_wrong[n] = max(best_wrong[n], p)
    t_match = threshold_at_fmr(best_wrong, args.target_fmr)
    # 3. view-consistency margin: 99th pct of genuine per-view gaps (genuine rarely flagged)
    gaps, view_imp = [], []
    for q in qv:
        if q.truth is not None:
            i = q.tree_ids.index(q.truth)
            for v in q.view_scores:
                gaps.append(float(np.delete(v, i).max() - v[i]) if len(v) > 1 else -1.0)
                if len(v) > 1:
                    view_imp.append(float(np.delete(v, i).max()))
        else:
            view_imp += [float(v.max()) for v in q.view_scores]
    margin = float(np.percentile(gaps, 99))
    t_view = threshold_at_fmr(np.array(view_imp), args.target_fmr)

    dup = json.loads(Path(args.duplicate).read_text())["threshold"] if args.duplicate else None
    cal = Calibration(species_threshold=float(sp["threshold"]), match_threshold=float(t_match), duplicate_cosine=dup,
                      global_threshold=float(t_global), target_fmr=args.target_fmr,
                      view_contradiction_margin=max(margin, 0.0), view_match_threshold=float(t_view),
                      fusers={"+".join(FEATS): fuser},
                      provenance={"fitted_on": f"{args.calib_species} val trees (identity-disjoint from train/test)",
                                  "n_val_queries": len(qv), "n_val_candidate_pairs": int(len(yv)),
                                  "embeddings": args.emb, "date": time.strftime("%Y-%m-%d")})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cal.save(args.out)

    # Evaluate the app's decide() on TEST
    report = {"calibration": json.loads(Path(args.out).read_text())}
    for name, use_views in (("decide_with_view_checks", True), ("decide_without_view_checks", False)):
        pred, truth, kinds = [], [], []
        for q in qt:
            order = np.argsort(-q.scores)[:args.k]
            feats = [(q.tree_ids[j], candidate_features(q.scores, q.view_scores, q.tree_ids, q.tree_ids[j]))
                     for j in order]
            d = decide(feats, cal, q.view_scores if use_views else None, q.tree_ids if use_views else None)
            kinds.append(d.kind)
            pred.append(d.tree_id if d.kind == "existing" else None)
            truth.append(q.truth)
        m = open_set_metrics(pred, truth)
        known = [k for k, t in zip(kinds, truth) if t is not None]
        new = [k for k, t in zip(kinds, truth) if t is None]
        m["uncertain_rate_known"] = known.count("uncertain") / max(len(known), 1)
        m["uncertain_rate_new"] = new.count("uncertain") / max(len(new), 1)
        report[name] = {k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()}
    # Gallery-size-aware global threshold (per-pair val impostors -> test gallery size)
    _, pair_imp = all_pairs(qv)
    n_test_gallery = int(np.median([len(q.tree_ids) for q in qt]))
    t_ga = threshold_for_gallery(pair_imp, n_test_gallery, args.target_fmr)
    m = open_set_metrics(*decide_global(qt, t_ga))
    report["global_threshold_gallery_aware"] = {"threshold": round(t_ga, 4), "n_gallery": n_test_gallery,
                                                **{k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()}}
    m = open_set_metrics(*decide_global(qt, t_global))
    report["global_threshold_max_impostor"] = {"threshold": round(t_global, 4),
                                               **{k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()}}
    report["pair_impostor_scores_val"] = {"n": int(len(pair_imp))}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "calibration"}, indent=1))
    print("thresholds", {"global": t_global, "match": t_match, "margin": margin, "view": t_view})


if __name__ == "__main__":
    main()
