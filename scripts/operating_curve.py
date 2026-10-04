"""Open-set operating curve on TEST (oracle sweep): for each false-match rate on
new-tree queries, the fraction of returning trees correctly auto-accepted.
This shows the achievable trade-off for choosing a target FMR; it is NOT a
deployable number (thresholds here are swept on test, not fitted on val).

Usage: python scripts/operating_curve.py --emb runs/reid/X/embeddings.npy --out runs/results/curve_X.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from hemlock_sentinel.evaluation.benchmarks import build_observations, decide_global, run_open_set
from hemlock_sentinel.evaluation.metrics import open_set_metrics
from hemlock_sentinel.evaluation.splits import read_manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb", required=True)
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", required=True)
    ap.add_argument("--views", type=int, default=3)
    args = ap.parse_args()
    recs = read_manifest(Path(args.data) / "manifest.csv")
    sp = json.loads((Path(args.data) / "splits.json").read_text())
    emb = np.load(args.emb)
    emb_of = {r.path: emb[i] for i, r in enumerate(recs)}
    qt = run_open_set(build_observations(recs, set(sp["test"]), "tsuga_canadensis", args.views, 2), emb_of,
                      repeats=20, seed=200)
    new_best = np.array([q.scores.max() for q in qt if q.truth is None])
    rows = []
    for fmr in (0.01, 0.02, 0.05, 0.1, 0.2, 0.3):
        t = float(np.quantile(new_best, 1 - fmr))
        m = open_set_metrics(*decide_global(qt, t))
        rows.append({"target_fmr_new_trees": fmr, "threshold": round(t, 4),
                     **{k: round(m[k], 4) for k in ("known_accuracy", "false_match_rate_new_trees",
                                                    "false_new_rate", "precision_existing")}})
    res = {"note": "ORACLE sweep on test; for trade-off visualisation only", "views": args.views, "curve": rows}
    Path(args.out).write_text(json.dumps(res, indent=2))
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
