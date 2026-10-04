"""Does local bark keypoint matching add identity information beyond the global embedding?

For hemlock val/test observations (3 views), each query is compared with its
top-k global candidates (k=5) in each of R enrolments. For every
(query, candidate) pair we record global/gap/agreement features and the
RootSIFT+RANSAC local score. A logistic fuser is fitted on val pairs with and
without the local feature; test ROC-AUC and FMR/false-new at the val-fitted
operating point are compared.

Also measures the cost: local feature extraction and per-pair matching time.

Usage: python scripts/evaluate_local.py --emb runs/reid/X/embeddings.npy --out runs/results/local.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from hemlock_sentinel.evaluation.benchmarks import build_observations, run_open_set
from hemlock_sentinel.evaluation.metrics import roc_auc
from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.reid.calibration import LogisticCalibrator
from hemlock_sentinel.reid.fusion import candidate_features
from hemlock_sentinel.reid.local_matching import KeypointMatcher


def pairs(qs, local_of, matcher, k):
    X, y, t_match = [], [], []
    for q in qs:
        order = np.argsort(-q.scores)[:k]
        for j in order:
            tid = q.tree_ids[j]
            f = candidate_features(q.scores, q.view_scores, q.tree_ids, tid)
            gpaths = q.gallery_paths[tid]
            t0 = time.perf_counter()
            f["local"] = matcher.score([local_of[p] for p in q.obs.paths], [local_of[p] for p in gpaths])
            t_match.append(time.perf_counter() - t0)
            X.append([f["global"], f["gap"], f["agreement"], f["local"]])
            y.append(int(q.truth == tid))
    return np.array(X), np.array(y), t_match


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb", required=True)
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()
    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    emb = np.load(args.emb)
    emb_of = {r.path: emb[i] for i, r in enumerate(recs)}
    matcher = KeypointMatcher()

    res = {"protocol": "hemlock val/test, 3-view observations, top-5 candidates, "
                       f"{args.repeats} enrolments; fuser fitted on val, evaluated on test"}
    data = {}
    t_ext = []
    for split, seed in (("val", 1), ("test", 2)):
        obs = build_observations(recs, set(splits[split]), "tsuga_canadensis", 3, seed)
        local_of = {}
        for o in obs:
            for p in o.paths:
                bgr = cv2.imread(p, cv2.IMREAD_REDUCED_COLOR_2)
                t0 = time.perf_counter()
                local_of[p] = matcher.extract(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
                t_ext.append(time.perf_counter() - t0)
        qs = run_open_set(obs, emb_of, repeats=args.repeats, seed=100 if split == "val" else 200)
        # gallery observation of an enrolled tree = its first observation by id
        # (same rule as splits.gallery_query_split)
        first_obs = {}
        for o in sorted(obs, key=lambda o: o.obs_id):
            first_obs.setdefault(o.tree_id, o)
        for q in qs:
            q.gallery_paths = {t: first_obs[t].paths for t in q.tree_ids}
        X, y, tm = pairs(qs, local_of, matcher, args.k)
        data[split] = (X, y)
        res[f"{split}_pairs"] = {"n": int(len(y)), "n_genuine": int(y.sum()),
                                 "local_genuine_median": float(np.median(X[y == 1, 3])) if y.sum() else None,
                                 "local_impostor_median": float(np.median(X[y == 0, 3])),
                                 "auc_local_only": round(roc_auc(X[y == 1, 3], X[y == 0, 3]), 4),
                                 "auc_global_only": round(roc_auc(X[y == 1, 0], X[y == 0, 0]), 4),
                                 "match_ms_per_pair_median": round(1000 * float(np.median(tm)), 2)}
    Xv, yv = data["val"]
    Xt, yt = data["test"]
    for name, cols in (("global+gap+agreement", [0, 1, 2]), ("global+gap+agreement+local", [0, 1, 2, 3])):
        lc = LogisticCalibrator(name.split("+")).fit(Xv[:, cols], yv)
        pt = lc.predict_proba(Xt[:, cols])
        res[f"fused_{name}"] = {"test_auc": round(roc_auc(pt[yt == 1], pt[yt == 0]), 4),
                                "coef": [round(c, 3) for c in lc.coef]}
    res["local_extract_ms_median"] = round(1000 * float(np.median(t_ext)), 1)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
