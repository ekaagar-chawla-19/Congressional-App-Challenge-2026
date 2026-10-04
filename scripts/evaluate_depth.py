"""Depth / structural evidence: how much could it help, and is consumer depth good enough?

Part A (real tree sizes): BarkNet records each tree's circumference at breast
height. For all hemlocks we ask: if the handheld measured DBH with error
sigma, what fraction of *different-tree* pairs could a DBH-consistency gate
reject while keeping 99 % of same-tree pairs? (Gate: |dDBH| <= 2.576*sqrt(2)*sigma.)

Part B (SYNTHETIC trunks, SimulatedDepth): DBH estimation error and the
same-tree vs different-tree separability (ROC-AUC) of the stem-profile
similarity, as a function of depth noise. These numbers describe the
algorithm on idealised trunks only — they are not evidence about real
hemlocks or any particular sensor.

Usage: python scripts/evaluate_depth.py --out runs/results/depth.json
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import numpy as np

from hemlock_sentinel.acquisition.mocks import SimulatedDepth, TrunkModel
from hemlock_sentinel.evaluation.metrics import roc_auc
from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.reid.local_matching import Intrinsics, profile_similarity, trunk_profile_from_depth


def part_a(recs, sigmas_cm):
    dbh = {}
    for r in recs:
        if r.species == "tsuga_canadensis":
            dbh[r.tree_id] = r.circumference_cm / np.pi
    d = np.array(list(dbh.values()))
    diffs = np.array([abs(a - b) for a, b in combinations(d, 2)])
    out = {"n_trees": len(d), "dbh_cm": {"min": round(float(d.min()), 1), "median": round(float(np.median(d)), 1),
                                          "max": round(float(d.max()), 1)},
           "n_impostor_pairs": int(len(diffs)), "gate": {}}
    for s in sigmas_cm:
        tol = 2.576 * np.sqrt(2) * s
        out["gate"][f"sigma_{s}cm"] = {"tolerance_cm": round(tol, 2),
                                       "impostor_pairs_rejected": round(float((diffs > tol).mean()), 4),
                                       "genuine_pairs_kept": 0.99}
    return out


def profile(seed, noise_b, offset, rng_seed, distance, dbh_m):
    trunk = TrunkModel.random(seed)
    trunk.dbh_m = dbh_m  # real hemlock size distribution -> realistic size overlap between trees
    sim = SimulatedDepth(trunk, distance_m=distance, noise_a=0.001, noise_b=noise_b,
                         height_offset_m=offset, seed=rng_seed)
    d = sim.capture_depth()
    return trunk_profile_from_depth(d.depth_m, Intrinsics(d.fx, d.fy, d.cx, d.cy)), sim.trunk


def part_b(noise_bs, real_dbh_cm, n_trees=30, distance=1.5):
    out = {}
    dbhs = np.random.default_rng(1).choice(np.asarray(real_dbh_cm) / 100, n_trees, replace=True)
    for b in noise_bs:
        rng = np.random.default_rng(0)
        prof = {}
        dbh_err = []
        for t in range(n_trees):
            for k in range(2):  # two captures per tree, different height offset and noise
                p, trunk = profile(t, b, float(rng.uniform(-0.1, 0.1)), 1000 * t + k, distance, float(dbhs[t]))
                prof[(t, k)] = p
                diam_true = float(np.median(trunk.diameter(np.linspace(0.3, 2.0, 30))))
                if np.any(~np.isnan(p.diameters)):
                    dbh_err.append(float(np.nanmedian(p.diameters)) - diam_true)
        gen = [profile_similarity(prof[(t, 0)], prof[(t, 1)], tol_m=0.01) for t in range(n_trees)]
        imp = [profile_similarity(prof[(a, 0)], prof[(c, 1)], tol_m=0.01)
               for a in range(n_trees) for c in range(n_trees) if a != c]
        gen, imp = np.array(gen), np.array(imp)
        gen, imp = gen[~np.isnan(gen)], imp[~np.isnan(imp)]
        out[f"noise_b_{b}"] = {
            "point_sigma_cm_at_distance": round(100 * (0.001 + b * distance ** 2), 2),
            "median_diameter_error_cm": round(100 * float(np.median(np.abs(dbh_err))), 2),
            "profile_auc_same_vs_different": round(roc_auc(gen, imp), 4),
            "n_genuine": int(len(gen)), "n_impostor": int(len(imp)),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", default="runs/results/depth.json")
    args = ap.parse_args()
    recs = read_manifest(Path(args.data) / "manifest.csv")
    real = sorted({r.tree_id: r.circumference_cm / np.pi for r in recs if r.species == "tsuga_canadensis"}.values())
    res = {"A_real_dbh_gate": part_a(recs, [0.5, 1.0, 2.0, 3.0, 5.0]),
           "B_SYNTHETIC_profile_matching": part_b([0.0, 0.0025, 0.005, 0.01], real)}
    res["B_SYNTHETIC_profile_matching"]["note"] = ("SYNTHETIC trunks (SimulatedDepth), DBH drawn from real BarkNet hemlock DBHs; stereo-style noise "
                                                   "sigma=a+b*z^2; not evidence about real trees/sensors")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
