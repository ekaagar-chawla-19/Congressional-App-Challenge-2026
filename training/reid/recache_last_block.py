"""Second-level cache for cheap controlled ablations: run the frozen prefix
(everything between the trunk cache and the LAST block) once, so ablation runs
only train the last block + head (see reid/backbone.last_block_split).

Usage: python training/reid/recache_last_block.py --cache runs/cache --out runs/cache_last
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from hemlock_sentinel.reid.backbone import last_block_split


def run(prefix, src, dst_path, bs=64):
    with torch.inference_mode():
        shape = tuple(prefix(torch.from_numpy(src[:1].astype(np.float32))).shape[1:])
        dst = np.lib.format.open_memmap(dst_path, "w+", np.float16, (len(src), *shape))
        for s in range(0, len(src), bs):
            dst[s:s + bs] = prefix(torch.from_numpy(src[s:s + bs].astype(np.float32))).numpy().astype(np.float16)
        dst.flush()
    return shape


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()
    torch.set_num_threads(args.threads)
    src, out = Path(args.cache), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((src / "meta.json").read_text())
    name = meta.get("backbone", "efficientnetv2_rw_m")
    kw = {"img_size": meta["size"]} if "dinov2" in name else {}
    prefix, _, _ = last_block_split(name, pretrained=True, **kw)
    prefix.eval()
    t0 = time.time()
    shape = run(prefix, np.load(src / "eval_trunk.npy", mmap_mode="r"), out / "eval_trunk.npy")
    run(prefix, np.load(src / "train_aug_trunk.npy", mmap_mode="r"), out / "train_aug_trunk.npy")
    (out / "train_aug_rows.npy").write_bytes((src / "train_aug_rows.npy").read_bytes())
    meta.update({"split": "last_block", "shape": list(shape), "recache_seconds": time.time() - t0})
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(meta)


if __name__ == "__main__":
    main()
