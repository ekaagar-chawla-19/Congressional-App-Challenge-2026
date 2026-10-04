"""How much do BarkNet images of the same tree overlap? (data-leakage audit)

All images of a BarkNet tree come from one session. If two of them show the
same bark patch, the "new view" queries are partly re-photographs of gallery
content and same-session results are optimistic. We count RootSIFT+RANSAC
inliers for every same-tree image pair of the hemlock val/test trees and for an
equal number of random different-tree pairs. The overlap threshold is the
99.9th percentile of different-tree inliers.

Usage: python scripts/analyze_overlap.py --out runs/results/overlap.json
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.reid.local_matching import KeypointMatcher


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", default="runs/results/overlap.json")
    args = ap.parse_args()
    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    ids = set(splits["val"]) | set(splits["test"])
    sel = [r for r in recs if r.tree_id in ids and r.species == "tsuga_canadensis"]
    m = KeypointMatcher()
    feats = {}
    for r in sel:
        feats[r.path] = m.extract(cv2.cvtColor(cv2.imread(r.path, cv2.IMREAD_REDUCED_COLOR_2), cv2.COLOR_BGR2RGB))
    by_tree = defaultdict(list)
    for r in sel:
        by_tree[r.tree_id].append(r.path)
    same = [(a, b) for ps in by_tree.values() for a, b in combinations(ps, 2)]
    rng = random.Random(0)
    paths = [r.path for r in sel]
    tree_of = {r.path: r.tree_id for r in sel}
    diff = []
    while len(diff) < len(same):
        a, b = rng.sample(paths, 2)
        if tree_of[a] != tree_of[b]:
            diff.append((a, b))
    s_in = np.array([m.inliers(feats[a], feats[b]) for a, b in same])
    d_in = np.array([m.inliers(feats[a], feats[b]) for a, b in diff])
    thr = float(np.percentile(d_in, 99.9))
    per_tree = defaultdict(list)
    for (a, _), v in zip(same, s_in):
        per_tree[tree_of[a]].append(v > thr)
    res = {"n_same_tree_pairs": int(len(s_in)), "n_different_tree_pairs": int(len(d_in)),
           "different_tree_inliers_p99_9": thr,
           "same_tree_pairs_overlapping_fraction": round(float((s_in > thr).mean()), 4),
           "trees_with_any_overlapping_pair": int(sum(any(v) for v in per_tree.values())),
           "n_trees": len(per_tree),
           "same_tree_inliers_percentiles": {p: float(np.percentile(s_in, p)) for p in (50, 90, 99)},
           "different_tree_inliers_percentiles": {p: float(np.percentile(d_in, p)) for p in (50, 90, 99)}}
    res["overlapping_pairs"] = [[a, b] for (a, b), v in zip(same, s_in) if v > thr]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    res.pop("overlapping_pairs")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
