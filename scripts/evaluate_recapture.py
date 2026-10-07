"""Re-identification of RE-PHOTOGRAPHED trees (Laval Tree-Bark-Re-Identification data).

Per species (red pine, elm), on TEST trees only (never trained on or calibrated on):

* image level: one-vs-all retrieval, identity = bark surface (same patch
  re-photographed under new lighting) and identity = tree;
* observation level (3-photo captures, as in the app), R random enrolments:
  half the trees are enrolled with one capture of surface 1; queries are
  - "same patch": other captures of the SAME surface (new light/angle) — what the
    app's north-anchored protocol produces on a revisit,
  - "other patch": captures of the tree's other surface,
  - "new tree": captures of non-enrolled trees;
* the app's full decision (fusion.decide) with (a) a calibration file fitted on
  BarkNet, applied unchanged, and (b) with --calibrate-on-val, thresholds and the
  fuser re-fitted on the CALIBRATION trees of this dataset (same camera/conditions,
  disjoint from test), to show what domain calibration buys.

Usage: python scripts/evaluate_recapture.py --emb runs/reid/X_barkreid/embeddings.npy --name X \
           --calibration runs/export/calibration.json --calibrate-on-val --out runs/results/recapture_X.json
"""

from __future__ import annotations

import argparse
import copy
import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

from hemlock_sentinel.evaluation.metrics import bootstrap_ci, retrieval_metrics, roc_auc
from hemlock_sentinel.evaluation.splits import make_observations, read_manifest
from hemlock_sentinel.reid.calibration import Calibration, LogisticCalibrator, threshold_at_fmr
from hemlock_sentinel.reid.fusion import candidate_features, decide
from hemlock_sentinel.reid.multiview import aggregate_mean, l2_normalize

SPECIES = ("pinus_resinosa", "ulmus_sp")
FEATS = ["global", "gap", "agreement"]


def queries_for(recs, emb, species, trees, repeats, seed):
    """Yield (scores, view_scores, names, truth, kind) over random enrolments."""
    rows = [i for i, r in enumerate(recs) if r.species == species and r.tree_id in trees]
    idx = {r.path: i for i, r in enumerate(recs)}
    obs = make_observations([recs[i] for i in rows], 3, seed)
    by_tree = defaultdict(list)
    for o in obs:
        by_tree[o.tree_id].append(o)
    agg = {o.obs_id: aggregate_mean(emb[[idx[p] for p in o.paths]]) for o in obs}
    views = {o.obs_id: l2_normalize(emb[[idx[p] for p in o.paths]]) for o in obs}
    rng = random.Random(seed)
    tree_list = sorted(by_tree)
    out = []
    for _ in range(repeats):
        rng.shuffle(tree_list)
        gal = {}
        for t in tree_list[: len(tree_list) // 2]:
            s1 = sorted((o for o in by_tree[t] if o.obs_id.split("#")[0].endswith("@s1")), key=lambda o: o.obs_id)
            gal[t] = rng.choice(s1).obs_id
        names = list(gal)
        G = np.stack([agg[gal[t]] for t in names])
        for t in tree_list:
            for o in by_tree[t]:
                if t in gal and o.obs_id == gal[t]:
                    continue
                kind = "new" if t not in gal else (
                    "same" if o.obs_id.split("#")[0] == gal[t].split("#")[0] else "other")
                out.append((G @ agg[o.obs_id], views[o.obs_id] @ G.T, names, t if t in gal else None, kind))
    return out, rows


def fit_domain_calibration(qs, base: Calibration, target_fmr=0.01) -> Calibration:
    """Same procedure as scripts/calibrate.py, on this dataset's calibration trees.
    Genuine = same-patch re-photographs (what the guided protocol produces)."""
    qs = [q for q in qs if q[4] in ("same", "new")]
    X, y, qid = [], [], []
    for n, (s, vs, names, truth, _) in enumerate(qs):
        for j in np.argsort(-s)[:5]:
            f = candidate_features(s, vs, names, names[j])
            X.append([f[c] for c in FEATS])
            y.append(int(truth == names[j]))
            qid.append(n)
    X, y = np.array(X), np.array(y)
    fuser = LogisticCalibrator(FEATS).fit(X, y)
    p = fuser.predict_proba(X)
    best_wrong = np.zeros(len(qs))
    for pi, yi, n in zip(p, y, qid):
        if not yi:
            best_wrong[n] = max(best_wrong[n], pi)
    imp = [np.delete(s, names.index(t)).max() if t else s.max() for s, _, names, t, _ in qs]
    gaps, view_imp = [], []
    for _s, vs, names, t, _ in qs:
        if t is not None:
            i = names.index(t)
            for v in vs:
                gaps.append(float(np.delete(v, i).max() - v[i]))
                view_imp.append(float(np.delete(v, i).max()))
        else:
            view_imp += [float(v.max()) for v in vs]
    cal = copy.deepcopy(base)
    cal.fusers = {"+".join(FEATS): fuser}
    cal.match_threshold = threshold_at_fmr(best_wrong, target_fmr)
    cal.global_threshold = threshold_at_fmr(np.array(imp), target_fmr)
    cal.view_contradiction_margin = max(float(np.percentile(gaps, 99)), 0.0)
    cal.view_match_threshold = threshold_at_fmr(np.array(view_imp), target_fmr)
    cal.provenance = {"fitted_on": "Laval bark re-ID calibration trees (disjoint from test)", "n_queries": len(qs)}
    return cal


def decision_summary(qs, cal):
    dec = {k: defaultdict(int) for k in ("same", "other", "new")}
    for s, vs, names, truth, kind in qs:
        top = np.argsort(-s)[:5]
        d = decide([(names[j], candidate_features(s, vs, names, names[j])) for j in top], cal, vs, names)
        if d.kind == "existing":
            dec[kind]["correct" if d.tree_id == truth else "wrong"] += 1
        else:
            dec[kind][d.kind] += 1
        dec[kind]["n"] += 1
    keys = ("correct", "wrong", "new", "uncertain")
    return {kind: {k: round(c.get(k, 0) / max(c["n"], 1), 4) for k in keys} | {"n": c["n"]}
            for kind, c in dec.items()}


def evaluate_species(recs, emb, species, test, val, cal, calibrate_on_val, repeats, seed):
    qs, rows = queries_for(recs, emb, species, test, repeats, seed)
    e = emb[rows]
    out = {"n_test_trees": len({recs[i].tree_id for i in rows}), "n_images": len(rows),
           "image_retrieval_same_surface": retrieval_metrics(e, np.array([recs[i].capture for i in rows])),
           "image_retrieval_tree": retrieval_metrics(e, np.array([recs[i].tree_id for i in rows]))}
    ranks = defaultdict(list)
    per_tree = defaultdict(list)
    gen = defaultdict(list)
    imp = []
    for s, _, names, truth, kind in qs:
        for j, t in enumerate(names):
            (gen[kind] if t == truth else imp).append(s[j])
        if truth is not None:
            r = int(np.nonzero(np.asarray(names)[np.argsort(-s)] == truth)[0][0]) + 1
            ranks[kind].append(r)
            if kind == "same":
                per_tree[truth].append(r == 1)

    def tk(r, k):
        return round(float(np.mean([x <= k for x in r])), 4)

    out["observation_3views"] = {
        "gallery_trees": len(qs[0][2]),
        "same_patch": {"top1": tk(ranks["same"], 1), "top5": tk(ranks["same"], 5), "n": len(ranks["same"]),
                       "top1_ci95_by_tree": [round(x, 4) for x in bootstrap_ci(
                           np.array([np.mean(v) for v in per_tree.values()]))]},
        "other_patch": {"top1": tk(ranks["other"], 1), "top5": tk(ranks["other"], 5), "n": len(ranks["other"])},
        "auc_same_patch_vs_wrong_tree": round(roc_auc(np.array(gen["same"]), np.array(imp)), 4),
        "auc_other_patch_vs_wrong_tree": round(roc_auc(np.array(gen["other"]), np.array(imp)), 4),
        "cosine_median": {"same_patch": round(float(np.median(gen["same"])), 4),
                          "other_patch": round(float(np.median(gen["other"])), 4),
                          "wrong_tree": round(float(np.median(imp)), 4)},
    }
    if cal is not None:
        out["decision_barknet_calibration"] = decision_summary(qs, cal)
        if calibrate_on_val:
            vq, _ = queries_for(recs, emb, species, val, repeats, seed + 1)
            dcal = fit_domain_calibration(vq, cal)
            out["decision_domain_calibration"] = decision_summary(qs, dcal)
            out["domain_calibration_thresholds"] = {"match": round(dcal.match_threshold, 4),
                                                    "global": round(dcal.global_threshold, 4)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--data", default="runs/data_barkreid")
    ap.add_argument("--calibration", default=None)
    ap.add_argument("--calibrate-on-val", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=20)
    args = ap.parse_args()
    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    emb = np.load(args.emb).astype(np.float32)
    cal = Calibration.load(args.calibration) if args.calibration else None
    res = {"name": args.name, "embeddings": args.emb, "calibration": args.calibration,
           "protocol": "Laval Tree-Bark-Re-Identification; TEST trees only (20 per species), never trained or "
                       "calibrated on; re-photographed at night under changed lighting/camera position, single "
                       "session; 3-photo observations; half the test trees enrolled per repeat"}
    for sp in SPECIES:
        res[sp] = evaluate_species(recs, emb, sp, set(splits["test"]), set(splits["val"]), cal,
                                   args.calibrate_on_val, args.repeats, 3)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    for sp in SPECIES:
        o = res[sp]
        ob = o["observation_3views"]
        print(f"{sp}: img(surface) top1 {o['image_retrieval_same_surface']['top1']} mAP "
              f"{o['image_retrieval_same_surface']['mAP']} | same-patch top1 {ob['same_patch']['top1']} "
              f"{ob['same_patch']['top1_ci95_by_tree']} top5 {ob['same_patch']['top5']} | other-patch top1 "
              f"{ob['other_patch']['top1']} | auc {ob['auc_same_patch_vs_wrong_tree']} / "
              f"{ob['auc_other_patch_vs_wrong_tree']} | cos {ob['cosine_median']}")
        for k in ("decision_barknet_calibration", "decision_domain_calibration"):
            if k in o:
                print(f"   {k}: {o[k]}")


if __name__ == "__main__":
    main()
