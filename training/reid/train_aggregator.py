"""Ablation: learned multi-view aggregation (attention pooling, small transformer) vs the plain mean.

Aggregators are trained on per-view embeddings of TRAIN trees only (random
3-view subsets of one tree are positives; SupCon loss on the aggregated
vectors), then evaluated with the same open-set protocol as the mean.

Usage: python training/reid/train_aggregator.py --emb runs/reid/X/embeddings.npy --out runs/results/aggregators.json
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

from hemlock_sentinel.evaluation.benchmarks import build_observations, closed_set_topk, decide_global, genuine_impostor, run_open_set
from hemlock_sentinel.evaluation.metrics import open_set_metrics, roc_auc
from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.reid.calibration import threshold_at_fmr
from hemlock_sentinel.reid.losses import SupConLoss
from hemlock_sentinel.reid.multiview import AttentionPool, MultiViewTransformer, aggregate_mean


def train(model, by_tree, emb, steps, views, rng, lr=1e-3):
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = SupConLoss(0.1)
    trees = [t for t, ix in by_tree.items() if len(ix) >= views]
    model.train()
    for _ in range(steps):
        chosen = rng.sample(trees, min(32, len(trees)))
        batch, labels = [], []
        for li, t in enumerate(chosen):
            for _ in range(2):  # two random subsets per tree -> positives
                batch.append(emb[rng.sample(by_tree[t], views)])
                labels.append(li)
        x = torch.from_numpy(np.stack(batch)).float()
        loss = loss_fn(model(x), torch.tensor(labels))
        opt.zero_grad()
        loss.backward()
        opt.step()
    return model.eval()


def evaluate(recs, splits, emb_of, agg, repeats):
    out = {}
    qv = run_open_set(build_observations(recs, set(splits["val"]), "tsuga_canadensis", 3, 1), emb_of, agg,
                      repeats=repeats, seed=100)
    qt = run_open_set(build_observations(recs, set(splits["test"]), "tsuga_canadensis", 3, 2), emb_of, agg,
                      repeats=repeats, seed=200)
    gv, iv = genuine_impostor(qv)
    gt, it = genuine_impostor(qt)
    out["closed_set_test"] = closed_set_topk(qt)
    out["closed_set_val"] = closed_set_topk(qv)
    out["roc_auc_test"] = round(roc_auc(gt, it), 4)
    t = threshold_at_fmr(iv, 0.01)
    m = open_set_metrics(*decide_global(qt, t))
    out["val_fmr_0.01"] = {k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb", required=True)
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    emb = np.load(args.emb).astype(np.float32)
    emb_of = {r.path: emb[i] for i, r in enumerate(recs)}
    by_tree = defaultdict(list)
    for i, r in enumerate(recs):
        if r.tree_id in set(splits["train"]):
            by_tree[r.tree_id].append(i)
    D = emb.shape[1]
    res = {"protocol": "aggregators trained on train trees only; evaluated on hemlock val/test (identity-disjoint)"}
    res["mean"] = evaluate(recs, splits, emb_of, aggregate_mean, args.repeats)
    res["mean"]["params"] = 0
    for name, model in (("attention_pool", AttentionPool(D)), ("transformer_2x256", MultiViewTransformer(D))):
        t0 = time.time()
        train(model, by_tree, emb, args.steps, 3, rng)
        train_s = time.time() - t0

        def agg(v, model=model):
            with torch.no_grad():
                return model(torch.from_numpy(np.asarray(v, np.float32))[None])[0].numpy()

        x = np.random.default_rng(0).normal(size=(3, D)).astype(np.float32)
        t0 = time.perf_counter()
        for _ in range(50):
            agg(x)
        lat_ms = (time.perf_counter() - t0) / 50 * 1000
        r = evaluate(recs, splits, emb_of, agg, args.repeats)
        r.update({"params": int(sum(p.numel() for p in model.parameters())), "train_seconds": round(train_s, 1),
                  "latency_ms_per_observation": round(lat_ms, 3)})
        res[name] = r
        print(name, json.dumps(r["closed_set_test"]), r["roc_auc_test"], flush=True)
    print("mean", json.dumps(res["mean"]["closed_set_test"]), res["mean"]["roc_auc_test"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
