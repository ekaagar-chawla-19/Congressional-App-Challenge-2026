"""Reproducible re-identification evaluation for one embedding file.

Usage:
    python scripts/evaluate_reid.py --emb runs/reid/subcenter/embeddings.npy --name subcenter \
        --out runs/results/subcenter.json

Every result records the split regime and that test identities were not in training.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from hemlock_sentinel.evaluation.benchmarks import (all_pairs, build_observations, closed_set_topk, decide_global,
                                                    genuine_impostor, run_open_set)
from hemlock_sentinel.evaluation.metrics import bootstrap_ci, open_set_metrics, retrieval_metrics, roc_auc
from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.reid.calibration import threshold_at_fmr
from hemlock_sentinel.reid.multiview import aggregate_mean, l2_normalize

HEMLOCK = "tsuga_canadensis"


def first_view(v: np.ndarray) -> np.ndarray:
    return l2_normalize(v[0])


def summarize_scores(x: np.ndarray) -> dict:
    return {p: round(float(np.percentile(x, p)), 4) for p in (1, 5, 25, 50, 75, 95, 99)} | {"n": int(len(x))}


def open_set_block(obs_val, obs_test, emb_of, aggregate, score_mode, fmrs=(0.01, 0.05), repeats=20):
    qv = run_open_set(obs_val, emb_of, aggregate, repeats=repeats, seed=100, score_mode=score_mode)
    qt = run_open_set(obs_test, emb_of, aggregate, repeats=repeats, seed=200, score_mode=score_mode)
    gv, iv = genuine_impostor(qv)
    gt, it = genuine_impostor(qt)
    gp, ip = all_pairs(qt)
    res = {"closed_set_test": closed_set_topk(qt), "closed_set_val": closed_set_topk(qv),
           "roc_auc_test": round(roc_auc(gt, it), 4), "roc_auc_val": round(roc_auc(gv, iv), 4),
           "roc_auc_all_pairs_test": round(roc_auc(gp, ip), 4),
           "roc_auc_note": "roc_auc_*: genuine vs BEST wrong tree per query (what the accept decision faces); "
                           "all_pairs: genuine vs every wrong tree (standard verification ROC)",
           "genuine_test": summarize_scores(gt), "impostor_test": summarize_scores(it), "thresholds": {}}
    # per-tree top-1 bootstrap CI (queries of one tree are correlated)
    per_tree = defaultdict(list)
    for q in qt:
        if q.truth is not None:
            per_tree[q.truth].append(q.rank == 1)
    res["closed_set_test"]["top1_ci95_by_tree"] = [round(x, 4) for x in
                                                   bootstrap_ci(np.array([np.mean(v) for v in per_tree.values()]))]
    # capture-level breakdown: queries from a different capture event (a second photo
    # session the same day) than the enrolled observation vs the same capture event
    first = {}
    for o in sorted(obs_test, key=lambda o: o.obs_id):
        first.setdefault(o.tree_id, o.obs_id.split("#")[0])
    by_cap = {"same_capture": [], "different_capture_same_day": []}
    for q in qt:
        if q.truth is not None:
            key = "same_capture" if q.obs.obs_id.split("#")[0] == first[q.truth] else "different_capture_same_day"
            by_cap[key].append(q.rank == 1)
    res["closed_set_test_by_capture"] = {k: {"top1": round(float(np.mean(v)), 4) if v else None, "n": len(v)}
                                         for k, v in by_cap.items()}
    for f in fmrs:
        t = threshold_at_fmr(iv, f)
        pred, truth = decide_global(qt, t)
        m = open_set_metrics(pred, truth)
        res["thresholds"][f"val_fmr_{f}"] = {"threshold": round(t, 4),
                                             **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}}
    return res, qv, qt


def strict_block(ov, ot, emb_of, pairs, repeats):
    out = {}
    for split, obs, seed in (("val", ov, 100), ("test", ot, 200)):
        qs = run_open_set(obs, emb_of, aggregate_mean, repeats=repeats, seed=seed)
        first = {}
        for o in sorted(obs, key=lambda o: o.obs_id):
            first.setdefault(o.tree_id, o)
        keep = []
        dropped = 0
        for q in qs:
            if q.truth is not None:
                g = first[q.truth].paths
                if any(frozenset((a, b)) in pairs for a in q.obs.paths for b in g):
                    dropped += 1
                    continue
            keep.append(q)
        out[split] = {**closed_set_topk(keep), "dropped_overlapping_queries": dropped}
        if split == "test":
            gp, ip = all_pairs(keep)
            out[split]["roc_auc_all_pairs"] = round(roc_auc(gp, ip), 4)
    return out


def device_analysis(recs, emb, rows):
    """Cosine of image pairs split by same/different tree and same/different device."""
    z = l2_normalize(emb[rows])
    s = z @ z.T
    trees = np.array([recs[i].tree_id for i in rows])
    dev = np.array([recs[i].device for i in rows])
    iu = np.triu_indices(len(rows), 1)
    same_t = trees[iu[0]] == trees[iu[1]]
    same_d = dev[iu[0]] == dev[iu[1]]
    sv = s[iu]
    out = {}
    for name, m in [("genuine", same_t), ("impostor_same_device", ~same_t & same_d),
                    ("impostor_cross_device", ~same_t & ~same_d)]:
        out[name] = {"mean": round(float(sv[m].mean()), 4), "p99": round(float(np.percentile(sv[m], 99)), 4),
                     "n": int(m.sum())}
    out["auc_vs_same_device_impostors"] = round(roc_auc(sv[same_t], sv[~same_t & same_d]), 4)
    out["auc_vs_cross_device_impostors"] = round(roc_auc(sv[same_t], sv[~same_t & ~same_d]), 4)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", required=True)
    ap.add_argument("--views", type=int, default=3)
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--quick", action="store_true", help="main protocol only (no ablations)")
    ap.add_argument("--hemlock-only", action="store_true", help="skip other-species metrics (partial embeddings)")
    ap.add_argument("--overlap", default="runs/results/overlap.json",
                    help="overlapping same-tree image pairs (scripts/analyze_overlap.py) for the strict regime")
    args = ap.parse_args()

    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    emb = np.load(args.emb)
    emb_of = {r.path: emb[i] for i, r in enumerate(recs)}
    val, test = set(splits["val"]), set(splits["test"])

    res = {"name": args.name, "embeddings": args.emb,
           "protocol": {"regime": "same tree / new bark region / same session (BarkNet has one session per tree)",
                        "test_identities_in_training": False, "species": HEMLOCK,
                        "views_per_observation": args.views, "enrolled_fraction": 0.5,
                        "repeats": args.repeats, "thresholds_fitted_on": "val split",
                        "n_val_trees": len([t for t in val if t.startswith("PRU-")]),
                        "n_test_trees": len([t for t in test if t.startswith("PRU-")])}}

    rows = {s: np.array([i for i, r in enumerate(recs) if r.tree_id in ids and r.species == HEMLOCK])
            for s, ids in (("val", val), ("test", test))}
    res["image_retrieval"] = {s: retrieval_metrics(emb[r], np.array([recs[i].tree_id for i in r]))
                              for s, r in rows.items()}
    if not args.hemlock_only:
        other = np.array([i for i, r in enumerate(recs) if r.tree_id in test and r.species != HEMLOCK])
        res["image_retrieval"]["test_other_species_pooled"] = retrieval_metrics(
            emb[other], np.array([recs[i].tree_id for i in other]))
    res["device_analysis_test"] = device_analysis(recs, emb, rows["test"])

    ov = build_observations(recs, val, HEMLOCK, args.views, seed=1)
    ot = build_observations(recs, test, HEMLOCK, args.views, seed=2)
    res["n_observations"] = {"val": len(ov), "test": len(ot)}
    res["open_set_mean"], _, _ = open_set_block(ov, ot, emb_of, aggregate_mean, "aggregate", repeats=args.repeats)

    if Path(args.overlap).exists():
        # STRICT regime: drop known queries containing any image that overlaps (RANSAC) an image
        # of the enrolled gallery observation of the same tree
        pairs = {frozenset(p) for p in json.loads(Path(args.overlap).read_text())["overlapping_pairs"]}
        res["open_set_strict_no_overlap"] = strict_block(ov, ot, emb_of, pairs, args.repeats)

    if not args.quick:
        abl = {}
        abl["single_view"], _, _ = open_set_block(ov, ot, emb_of, first_view, "aggregate", repeats=args.repeats)
        abl["max_pair_late_fusion"], _, _ = open_set_block(ov, ot, emb_of, aggregate_mean, "max_pair",
                                                           repeats=args.repeats)
        for v in (1, 5):
            ovv = build_observations(recs, val, HEMLOCK, v, seed=1)
            otv = build_observations(recs, test, HEMLOCK, v, seed=2)
            abl[f"mean_{v}_views"], _, _ = open_set_block(ovv, otv, emb_of, aggregate_mean, "aggregate",
                                                          repeats=args.repeats)
        res["aggregation_ablation"] = abl

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    o = res["open_set_mean"]
    print(json.dumps({"image_retrieval": res["image_retrieval"], "closed_set_test": o["closed_set_test"],
                      "roc_auc_test": o["roc_auc_test"], "fmr1%": o["thresholds"]["val_fmr_0.01"]}, indent=1))


if __name__ == "__main__":
    main()
