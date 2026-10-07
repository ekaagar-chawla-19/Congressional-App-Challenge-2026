"""Turn the app's database (field captures) into a training/evaluation dataset.

Every observation the app stored with a confirmed tree ID becomes one capture
event; every identity (trunk) view becomes one image row. The session is the
capture DATE, so repeat visits on different days are different sessions. This
is the hemlock-specific, multi-day dataset that no public source provides.

Only use observations whose tree ID you trust: by default those the user
confirmed or corrected, plus automatic decisions, unless --confirmed-only.
Tag the trees physically (numbered tags) and correct any wrong IDs in the app
before exporting, so labels are ground truth rather than model output.

Splits are by TREE (train / val / test), so test trees are never trained on.

Usage:
    python scripts/export_field_data.py --db runs/app/trees.sqlite --blobs runs/app/blobs --out runs/data_field
then: cache_trunk.py --data runs/data_field ..., train_tail.py --extra-data runs/data_field ...,
      scripts/evaluate_field.py --data runs/data_field --emb ...
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path

from hemlock_sentinel.acquisition.mocks import LocalFileStorage
from hemlock_sentinel.acquisition.protocol import is_identity_view
from hemlock_sentinel.evaluation.splits import ImageRecord, split_identities, write_manifest

TRUSTED = ("user_confirmed", "user_corrected", "confirmed")
AUTOMATIC = ("existing", "new")


def export(db: str, blobs: str, out: str, confirmed_only: bool = False, seed: int = 17,
           fractions=(0.6, 0.2, 0.2), min_sessions_for_test: int = 2) -> dict:
    storage = LocalFileStorage(blobs)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    ok = TRUSTED if confirmed_only else TRUSTED + AUTOMATIC
    rows = con.execute(
        "SELECT o.observation_id, o.tree_id, o.timestamp, t.species, v.view_index, v.view_type, v.image_key "
        "FROM observations o JOIN trees t ON t.tree_id = o.tree_id JOIN views v ON v.observation_id = o.observation_id "
        f"WHERE o.tree_id IS NOT NULL AND t.merged_into IS NULL AND o.decision IN ({','.join('?' * len(ok))}) "
        "AND v.image_key IS NOT NULL ORDER BY o.tree_id, o.timestamp, v.view_index", ok).fetchall()
    recs = []
    for r in rows:
        if not is_identity_view(r["view_type"]):
            continue
        day = dt.datetime.fromtimestamp(r["timestamp"], dt.timezone.utc).strftime("%Y%m%d")
        recs.append(ImageRecord(storage.path(r["image_key"]), r["tree_id"], r["species"], day,
                                f"{r['tree_id']}@{r['observation_id']}", "app", 0.0, int(r["view_index"])))
    if not recs:
        raise SystemExit("no exportable observations")
    outp = Path(out)
    outp.mkdir(parents=True, exist_ok=True)
    write_manifest(recs, outp / "manifest.csv")
    sessions = {}
    for r in recs:
        sessions.setdefault(r.tree_id, set()).add(r.session)
    # trees seen on >= 2 different days are the valuable ones: keep them for val/test first
    multi = sorted(t for t, s in sessions.items() if len(s) >= min_sessions_for_test)
    single = sorted(t for t, s in sessions.items() if len(s) < min_sessions_for_test)
    tr, va, te = split_identities(multi, fractions, seed)
    splits = {"train": tr + single, "val": va, "test": te, "held_out_species": [], "seed": seed,
              "note": "split by tree; trees visited on a single day are training-only"}
    (outp / "splits.json").write_text(json.dumps(splits, indent=2))
    stats = {"images": len(recs), "trees": len(sessions), "trees_with_repeat_visits": len(multi),
             "observations": len({r.capture for r in recs}), "train/val/test trees": [len(tr) + len(single), len(va), len(te)]}
    print(json.dumps(stats))
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--blobs", required=True)
    ap.add_argument("--out", default="runs/data_field")
    ap.add_argument("--confirmed-only", action="store_true")
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()
    export(args.db, args.blobs, args.out, args.confirmed_only, args.seed)


if __name__ == "__main__":
    main()
