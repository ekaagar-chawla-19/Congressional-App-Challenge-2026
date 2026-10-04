"""Build the BarkNet manifest and the identity-disjoint splits used by every experiment.

Usage:
    python scripts/prepare_barknet.py --root /path/to/barknet --out runs/data

Writes manifest.csv and splits.json. Split rules: see
src/hemlock_sentinel/evaluation/splits.py. THO and EPR are held out entirely
(never trained on) to measure unknown-species rejection.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from hemlock_sentinel.evaluation.splits import parse_barknet, split_identities, write_manifest
from hemlock_sentinel.species.labels import BARKNET_CODES, HELD_OUT_SPECIES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="runs/data")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--fractions", type=float, nargs=3, default=(0.5, 0.2, 0.3))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    recs = parse_barknet(args.root, BARKNET_CODES)
    write_manifest(recs, out / "manifest.csv")

    trees_by_species = defaultdict(set)
    for r in recs:
        trees_by_species[r.species].add(r.tree_id)

    splits = {"train": [], "val": [], "test": [], "held_out_species": [], "seed": args.seed,
              "fractions": list(args.fractions)}
    for sp in sorted(trees_by_species):
        ids = sorted(trees_by_species[sp])
        if sp in HELD_OUT_SPECIES:
            splits["held_out_species"].extend(ids)
            continue
        if len(ids) < 5:  # too few trees to split by identity: training only
            splits["train"].extend(ids)
            continue
        tr, va, te = split_identities(ids, tuple(args.fractions), args.seed)
        splits["train"] += tr
        splits["val"] += va
        splits["test"] += te

    stats = defaultdict(lambda: defaultdict(int))
    split_of = {t: k for k in ("train", "val", "test", "held_out_species") for t in splits[k]}
    for r in recs:
        stats[r.species][split_of[r.tree_id] + "_images"] += 1
    for sp, ids in trees_by_species.items():
        for t in ids:
            stats[sp][split_of[t] + "_trees"] += 1
    splits["stats"] = {k: dict(v) for k, v in stats.items()}
    (out / "splits.json").write_text(json.dumps(splits, indent=2))
    print(json.dumps(splits["stats"], indent=2))
    assert not (set(splits["train"]) & set(splits["test"])), "identity leakage"
    assert not (set(splits["train"]) & set(splits["val"])), "identity leakage"


if __name__ == "__main__":
    main()
