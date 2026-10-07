"""The test that matters: recognise a tree on a LATER DAY than it was enrolled.

For each test tree with captures on >= 2 different days: the gallery holds its
EARLIEST capture; queries are its captures from later days. Half the test trees
are enrolled per repeat; captures of the other half are "new tree" queries.
Reports ranking accuracy by days elapsed and the app's full decision with a
given calibration (fit it with scripts/calibrate.py on the val trees of the
same field dataset).

Usage: python scripts/evaluate_field.py --data runs/data_field --emb runs/reid/X_field/embeddings.npy \
           --calibration runs/export/calibration_field.json --out runs/results/field_X.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

from hemlock_sentinel.evaluation.metrics import roc_auc
from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.reid.calibration import Calibration
from hemlock_sentinel.reid.fusion import candidate_features, decide
from hemlock_sentinel.reid.multiview import aggregate_mean, l2_normalize


def days_between(a: str, b: str) -> int:
    return (dt.datetime.strptime(b, "%Y%m%d") - dt.datetime.strptime(a, "%Y%m%d")).days


def evaluate(recs, emb, trees, cal=None, repeats=20, seed=0):
    idx = defaultdict(list)
    for i, r in enumerate(recs):
        if r.tree_id in trees:
            idx[(r.tree_id, r.capture, r.session)].append(i)
    caps = defaultdict(list)  # tree -> [(session, capture, rows)]
    for (t, c, s), rows in idx.items():
        caps[t].append((s, c, rows))
    trees = sorted(t for t, cs in caps.items() if len({s for s, _, _ in cs}) >= 2)
    if len(trees) < 2:
        raise SystemExit("need >= 2 test trees with captures on >= 2 different days")
    agg = {c: aggregate_mean(emb[rows]) for cs in caps.values() for _, c, rows in cs}
    views = {c: l2_normalize(emb[rows]) for cs in caps.values() for _, c, rows in cs}
    rng = random.Random(seed)
    ranks = defaultdict(list)
    gen, imp = [], []
    dec = {k: defaultdict(int) for k in ("later_day", "new")}
    for _ in range(repeats):
        order = trees[:]
        rng.shuffle(order)
        enrolled = order[: max(1, len(order) // 2)]
        first = {t: min(caps[t]) for t in enrolled}  # earliest session
        names = list(enrolled)
        G = np.stack([agg[first[t][1]] for t in names])
        for t in order:
            for s, c, _ in caps[t]:
                if t in first and s == first[t][0]:
                    continue  # same-day captures are not the question here
                sc, vs = G @ agg[c], views[c] @ G.T
                truth = t if t in first else None
                for j, n in enumerate(names):
                    (gen if n == truth else imp).append(sc[j])
                if truth is not None:
                    d = days_between(first[t][0], s)
                    bucket = "<=7d" if d <= 7 else "8-60d" if d <= 60 else "61-180d" if d <= 180 else ">180d"
                    ranks[bucket].append(int(np.nonzero(np.asarray(names)[np.argsort(-sc)] == truth)[0][0]) + 1)
                if cal is not None:
                    top = np.argsort(-sc)[:5]
                    r = decide([(names[j], candidate_features(sc, vs, names, names[j])) for j in top], cal, vs, names)
                    k = "later_day" if truth is not None else "new"
                    dec[k]["correct" if r.kind == "existing" and r.tree_id == truth else
                           "wrong" if r.kind == "existing" else r.kind] += 1
                    dec[k]["n"] += 1
    allr = [x for v in ranks.values() for x in v]
    out = {"n_trees": len(trees), "gallery_trees": max(1, len(trees) // 2),
           "later_day_top1": round(float(np.mean([r == 1 for r in allr])), 4),
           "later_day_top5": round(float(np.mean([r <= 5 for r in allr])), 4),
           "n_queries": len(allr),
           "by_days_elapsed": {k: {"top1": round(float(np.mean([r == 1 for r in v])), 4), "n": len(v)}
                               for k, v in sorted(ranks.items())},
           "auc_later_day_vs_wrong_tree": round(roc_auc(np.array(gen), np.array(imp)), 4)}
    if cal is not None:
        keys = ("correct", "wrong", "new", "uncertain")
        out["decision"] = {k: {x: round(c.get(x, 0) / max(c["n"], 1), 4) for x in keys} | {"n": c["n"]}
                           for k, c in dec.items()}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="runs/data_field")
    ap.add_argument("--emb", required=True)
    ap.add_argument("--calibration", default=None)
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    res = evaluate(recs, np.load(args.emb).astype(np.float32), set(splits[args.split]),
                   Calibration.load(args.calibration) if args.calibration else None)
    res["protocol"] = "enrol earliest day, query later days; trees never trained on"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
