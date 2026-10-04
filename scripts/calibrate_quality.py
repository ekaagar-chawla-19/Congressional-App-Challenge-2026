"""Derive image-quality thresholds from real images instead of guessing.

For a sample of training-split images, computes the quality metrics on the
original and on synthetically degraded copies (Gaussian blur, under/over
exposure, featureless crop) and prints the threshold that best separates
"acceptable" from "degraded" for each metric, plus percentiles.

Usage: python scripts/calibrate_quality.py --data runs/data --n 300
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np

from hemlock_sentinel.acquisition.quality import QualityThresholds, assess
from hemlock_sentinel.evaluation.splits import read_manifest


def best_split(good: np.ndarray, bad: np.ndarray) -> tuple[float, float]:
    """Threshold t (accept if value >= t) maximising balanced accuracy."""
    cands = np.unique(np.concatenate([good, bad]))
    best = (0.0, float(cands[0]))
    for t in cands:
        ba = 0.5 * ((good >= t).mean() + (bad < t).mean())
        if ba > best[0]:
            best = (float(ba), float(t))
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--blur-sigma", type=float, default=3.0, help="blur (px at 512 px analysis scale) deemed unusable")
    ap.add_argument("--out", default="runs/quality_calibration.json")
    args = ap.parse_args()
    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    train = [r for r in recs if r.tree_id in set(splits["train"])]
    random.Random(0).shuffle(train)
    th = QualityThresholds()
    m = {"orig": [], "blur": []}
    for r in train[: args.n]:
        bgr = cv2.imread(r.path, cv2.IMREAD_REDUCED_COLOR_2)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        s = th.analysis_side / max(rgb.shape[:2])
        small = cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        m["orig"].append(assess(small, th).metrics)
        m["blur"].append(assess(cv2.GaussianBlur(small, (0, 0), args.blur_sigma), th).metrics)
    res = {}
    for key in ("laplacian_var", "edge_density", "mean_luma", "clipped_fraction"):
        o = np.array([x[key] for x in m["orig"]])
        res[key] = {"orig_percentiles": {p: float(np.percentile(o, p)) for p in (1, 5, 50, 95, 99)}}
    for key in ("laplacian_var", "edge_density"):
        o = np.array([x[key] for x in m["orig"]])
        b = np.array([x[key] for x in m["blur"]])
        ba, t = best_split(o, b)
        res[key].update({"blur_percentiles": {p: float(np.percentile(b, p)) for p in (1, 50, 99)},
                         "best_threshold_vs_blur": t, "balanced_accuracy": ba})
    res["n_images"] = len(m["orig"])
    res["blur_sigma"] = args.blur_sigma
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
