"""Manifest + tree-disjoint split for the Laval Tree-Bark-Re-Identification dataset.

Robert, Dallaire & Giguère (arXiv:1912.03221), MIT license,
https://github.com/ulaval-damas/Tree-Bark-Re-Identification (Bark Id *Crop* sets).
Red pine (RP) and elm (EL): 50 trees each, 2 distinct bark surfaces per tree,
12 photos per surface, taken at night with the lamp and the phone (LG Q6) moved
between shots. So every surface is genuinely RE-PHOTOGRAPHED under strong
lighting/viewpoint change, but within one session (not on different days).

Split per species, by tree: 20 train (fine-tuning) / 10 calibration (thresholds
for this camera + conditions) / 20 test. Every reported number uses test trees.

The "capture" field is the bark surface, so a 3-photo observation never mixes
surfaces.

Usage: python scripts/prepare_bark_reid.py --root /data/barkreid --out runs/data_barkreid
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from hemlock_sentinel.evaluation.splits import ImageRecord, split_identities, write_manifest

SPECIES = {"RP": "pinus_resinosa", "EL": "ulmus_sp"}
DIR_RE = re.compile(r"^(RP|EL)-tree-(\d+)_frame-(\d+)$")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="runs/data_barkreid")
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()
    recs = []
    for d in sorted(Path(args.root).glob("*-CropDataset/*")):
        m = DIR_RE.match(d.name)
        if not m:
            continue
        code, tree, surface = m.groups()
        tid = f"{code}-{tree}"
        for p in sorted(d.glob("*.jpg"), key=lambda p: int(re.findall(r"\d+", p.stem)[-1])):
            recs.append(ImageRecord(str(p), tid, SPECIES[code], "night", f"{tid}@s{surface}", "LG Q6", 0.0,
                                    int(re.findall(r"\d+", p.stem)[-1])))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_manifest(recs, out / "manifest.csv")
    splits = {"train": [], "val": [], "test": [], "held_out_species": [], "seed": args.seed}
    for code in SPECIES:
        ids = sorted({r.tree_id for r in recs if r.tree_id.startswith(code + "-")})
        tr, va, te = split_identities(ids, (0.4, 0.2, 0.4), args.seed)
        splits["train"] += tr
        splits["val"] += va
        splits["test"] += te
    (out / "splits.json").write_text(json.dumps(splits, indent=2))
    print(f"{len(recs)} images, {len({r.tree_id for r in recs})} trees, "
          f"{len({r.capture for r in recs})} surfaces; train {len(splits['train'])} / calibration {len(splits['val'])} / test {len(splits['test'])} trees")


if __name__ == "__main__":
    main()
