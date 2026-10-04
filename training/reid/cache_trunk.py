"""Cache frozen-trunk feature maps so the tail of EfficientNetV2-M can be fine-tuned on CPU.

Why: full fine-tuning of efficientnetv2_rw_m measured ~0.4 s/img (fwd+bwd, 224 px)
on the 4-core CPU available to this project, i.e. >30 min/epoch. Stages 0-4
(15 % of parameters) are frozen; their output is cached once (fp16 memmap) for
each training augmentation and once (deterministic centre crop) for every
evaluation image. Stage 5 + conv_head (85 % of parameters) + GeM + BN are
then fine-tuned from the cache. With a GPU, use training/reid/train.py
--full instead.

Usage:
    python training/reid/cache_trunk.py --data runs/data --out runs/cache --size 320 --train-augs 4
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset
from torchvision.transforms import v2 as T

from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.preprocessing import IMAGENET_MEAN, IMAGENET_STD, resize_short_center_crop
from hemlock_sentinel.reid.backbone import trunk_tail


def load_rgb(path: str) -> np.ndarray:
    # BarkNet crops are ~1500x3200; decoding at 1/2 resolution is ~4x faster and
    # still leaves the short side well above the 320-400 px we need.
    bgr = cv2.imread(path, cv2.IMREAD_REDUCED_COLOR_2)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


class CacheSet(Dataset):
    def __init__(self, items, size, train_augs):
        self.items = items  # (row_index, path, is_train)
        self.size = size
        self.train_augs = train_augs
        self.aug = T.Compose([
            T.RandomResizedCrop(size, scale=(0.35, 1.0), ratio=(0.75, 1.33), antialias=True),
            T.RandomHorizontalFlip(),
            T.RandomRotation(15),
            T.ColorJitter(0.3, 0.3, 0.2, 0.03),
        ])

    def __len__(self):
        return len(self.items)

    def norm(self, x: torch.Tensor) -> torch.Tensor:
        return (x - torch.tensor(IMAGENET_MEAN)[:, None, None]) / torch.tensor(IMAGENET_STD)[:, None, None]

    def __getitem__(self, i):
        idx, path, is_train = self.items[i]
        rgb = load_rgb(path)
        center = torch.from_numpy(resize_short_center_crop(rgb, self.size)).permute(2, 0, 1).float() / 255
        views = [self.norm(center)]
        if is_train:
            # bark strip -> short side ~1.25x size so random crops cover different bark regions
            s = self.size * 1.25 / min(rgb.shape[:2])
            base = torch.from_numpy(cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)).permute(2, 0, 1)
            for _ in range(self.train_augs):
                views.append(self.norm(self.aug(base).float() / 255))
        return idx, torch.stack(views)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", default="runs/cache")
    ap.add_argument("--size", type=int, default=320)
    ap.add_argument("--train-augs", type=int, default=4)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--backbone", default="efficientnetv2_rw_m")
    args = ap.parse_args()
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)

    data, out = Path(args.data), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    recs = read_manifest(data / "manifest.csv")
    splits = json.loads((data / "splits.json").read_text())
    train_ids = set(splits["train"])

    kw = {"img_size": args.size} if "dinov2" in args.backbone else {}
    trunk, _, _, frozen = trunk_tail(args.backbone, pretrained=True, **kw)
    trunk = trunk.eval()
    with torch.no_grad():
        feat_shape = tuple(trunk(torch.zeros(1, 3, args.size, args.size)).shape[1:])

    items = [(i, r.path, r.tree_id in train_ids) for i, r in enumerate(recs)]
    n_train = sum(1 for it in items if it[2])
    eval_mm = np.lib.format.open_memmap(out / "eval_trunk.npy", "w+", np.float16, (len(recs), *feat_shape))
    aug_mm = np.lib.format.open_memmap(out / "train_aug_trunk.npy", "w+", np.float16,
                                       (n_train * args.train_augs, *feat_shape))
    aug_rows = []  # manifest row for each augmented sample
    loader = DataLoader(CacheSet(items, args.size, args.train_augs), batch_size=1, num_workers=args.workers)
    t0 = time.time()
    a = 0
    with torch.no_grad():
        for k, (idx, views) in enumerate(loader):
            f = trunk(views[0]).numpy().astype(np.float16)
            eval_mm[int(idx)] = f[0]
            if len(f) > 1:
                aug_mm[a:a + len(f) - 1] = f[1:]
                aug_rows += [int(idx)] * (len(f) - 1)
                a += len(f) - 1
            if k % 200 == 0:
                print(f"{k}/{len(items)} {time.time() - t0:.0f}s", flush=True)
    eval_mm.flush()
    aug_mm.flush()
    np.save(out / "train_aug_rows.npy", np.asarray(aug_rows, dtype=np.int64))
    meta = {"size": args.size, "backbone": args.backbone, "trunk_frozen_units": frozen,
            "shape": [int(x) for x in feat_shape],
            "train_augs": args.train_augs, "n_images": len(recs), "n_train_images": n_train,
            "seconds": time.time() - t0}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(meta)


if __name__ == "__main__":
    main()
