"""Calibrate the duplicate-view threshold for the deployed model.

"Duplicate" = the user re-shot the same view instead of moving to the next
position. We simulate re-shoots of real (training-split) bark images with
small camera jitter (shift <= 6 %, rotation <= 3 deg, scale +-4 %, brightness
+-12 %) and compare their embedding cosine against genuine *next views*
(different images of the same tree). The threshold is set halfway (in cosine)
between the 1st percentile of re-shoots and the 99th percentile of next views,
and both distributions are reported.

Usage: python scripts/calibrate_duplicate.py --model runs/export/hemlock.onnx --out runs/results/duplicate.json
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.pipeline.runtime import OnnxRuntime
from hemlock_sentinel.preprocessing import decode_image, to_network_input
from hemlock_sentinel.reid.multiview import l2_normalize


def jitter(rgb: np.ndarray, rng: random.Random) -> np.ndarray:
    h, w = rgb.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-3, 3), rng.uniform(0.96, 1.04))
    M[:, 2] += (rng.uniform(-0.06, 0.06) * w, rng.uniform(-0.06, 0.06) * h)
    out = cv2.warpAffine(rgb, M, (w, h), borderMode=cv2.BORDER_REFLECT)
    return np.clip(out.astype(np.float32) * rng.uniform(0.88, 1.12), 0, 255).astype(np.uint8)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", default="runs/results/duplicate.json")
    ap.add_argument("--n-trees", type=int, default=30)
    args = ap.parse_args()
    rng = random.Random(0)
    recs = read_manifest(Path(args.data) / "manifest.csv")
    sp = json.loads((Path(args.data) / "splits.json").read_text())
    by_tree = defaultdict(list)
    for r in recs:
        if r.tree_id in set(sp["train"]):
            by_tree[r.tree_id].append(r.path)
    trees = rng.sample(sorted(by_tree), min(args.n_trees, len(by_tree)))
    rt = OnnxRuntime(args.model, threads=4)

    def emb(rgb):
        return l2_normalize(rt.run(to_network_input(rgb, rt.input_size)[None])[0][0])

    reshoot, nextview = [], []
    for t in trees:
        a, b, c2 = rng.sample(by_tree[t], 3)
        ra = decode_image(Path(a).read_bytes())
        ea = emb(ra)
        reshoot.append(float(ea @ emb(jitter(ra, rng))))
        nextview.append(float(ea @ emb(decode_image(Path(b).read_bytes()))))
        nextview.append(float(ea @ emb(decode_image(Path(c2).read_bytes()))))
    r1, n99 = float(np.percentile(reshoot, 1)), float(np.percentile(nextview, 99))
    res = {"n": len(trees), "reshoot_cos": {p: round(float(np.percentile(reshoot, p)), 4) for p in (1, 5, 50)},
           "next_view_cos": {p: round(float(np.percentile(nextview, p)), 4) for p in (50, 95, 99)},
           "threshold": round(n99, 4), "separable": r1 > n99,
           "next_view_max": round(float(np.max(nextview)), 4),
           # hard rejection only above anything a genuine next view ever reached
           "hard_threshold": round(max(0.97, float(np.max(nextview)) + 0.02), 4),
           "reshoots_caught_at_threshold": round(float((np.asarray(reshoot) > n99).mean()), 4),
           "note": "re-shoots simulated with small jitter on training-split images"}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
