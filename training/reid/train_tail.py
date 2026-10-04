"""Fine-tune the tail of EfficientNetV2-M (stage 5 + conv_head) + GeM + BN from cached trunk features.

Identities: every training-split tree of every species (multi-species training
follows MiewID's finding that multispecies models beat single-species ones;
whether that transfers to trees is tested, not assumed — see
docs/experiments.md E-loss/E-multispecies).

Model selection: the epoch with the best hemlock *validation* mAP (val trees
are identity-disjoint from train and test). Test trees are never touched here.

Usage:
    python training/reid/train_tail.py --cache runs/cache --data runs/data --loss subcenter_arcface \
        --epochs 6 --out runs/reid/subcenter
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import timm
import torch
from torch import nn

from hemlock_sentinel.evaluation.metrics import retrieval_metrics
from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.reid.backbone import last_block_split, trunk_tail
from hemlock_sentinel.reid.embedding import EmbeddingHead
from hemlock_sentinel.reid.losses import build_loss

TRUNK_STAGES = 5


class Tail(nn.Module):
    """Trainable tail + GeM + BN. For EfficientNetV2-M the parameter names
    (stage5 / conv_head / bn2 / head) are what scripts/export_model.py maps."""

    def __init__(self, backbone: str = "efficientnetv2_rw_m", pretrained: bool = True, gem_p: float = 3.0,
                 train_stage5: bool = True, img_size: int | None = None, split: str = "trunk"):
        super().__init__()
        self.backbone = backbone
        self.split = split
        if split == "last_block":  # controlled-ablation regime
            kw = {"img_size": img_size} if "dinov2" in backbone else {}
            _, self.tail, dim = last_block_split(backbone, pretrained=pretrained, **kw)
        elif backbone.startswith("efficientnetv2"):
            m = timm.create_model(backbone, pretrained=pretrained, num_classes=0, global_pool="")
            self.stage5 = m.blocks[TRUNK_STAGES:]
            self.conv_head, self.bn2 = m.conv_head, m.bn2
            dim = m.num_features
            for p in self.stage5.parameters():
                p.requires_grad_(train_stage5)
        else:
            kw = {"img_size": img_size} if img_size else {}
            _, self.tail, dim, _ = trunk_tail(backbone, pretrained=pretrained, **kw)
        self.head = EmbeddingHead(dim, gem_p)
        self.dim = dim

    def forward(self, x):
        if self.split == "trunk" and self.backbone.startswith("efficientnetv2"):
            return self.head(self.bn2(self.conv_head(self.stage5(x))))
        return self.head(self.tail(x))

    def param_groups(self):
        if self.split == "trunk" and self.backbone.startswith("efficientnetv2"):
            bb = [p for p in self.stage5.parameters() if p.requires_grad] + \
                list(self.conv_head.parameters()) + list(self.bn2.parameters())
        else:
            bb = list(self.tail.parameters())
        return bb, list(self.head.parameters())


def pk_batches(labels: np.ndarray, p: int, k: int, rng: random.Random):
    """Batches of p identities x k samples (sampling with replacement inside small identities)."""
    by = defaultdict(list)
    for i, l in enumerate(labels):
        by[int(l)].append(i)
    ids = list(by)
    n_batches = len(labels) // (p * k)
    for _ in range(n_batches):
        chosen = rng.sample(ids, min(p, len(ids)))
        idx = []
        for c in chosen:
            pool = by[c]
            idx += rng.sample(pool, k) if len(pool) >= k else [rng.choice(pool) for _ in range(k)]
        yield idx


@torch.no_grad()
def embed(tail: Tail, feats: np.ndarray, rows: np.ndarray, bs: int = 64) -> np.ndarray:
    tail.eval()
    out = []
    for s in range(0, len(rows), bs):
        x = torch.from_numpy(feats[rows[s:s + bs]].astype(np.float32))
        out.append(tail(x).numpy())
    return np.concatenate(out) if out else np.zeros((0, tail.dim), np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="runs/cache")
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", required=True)
    ap.add_argument("--loss", default="subcenter_arcface")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--p", type=int, default=16)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--lr-head", type=float, default=1e-3)
    ap.add_argument("--lr-backbone", type=float, default=1e-4)
    ap.add_argument("--s", type=float, default=30.0)
    ap.add_argument("--m-max", type=float, default=0.5)
    ap.add_argument("--subcenters", type=int, default=3)
    ap.add_argument("--hemlock-only", action="store_true", help="train identities: hemlock only (ablation)")
    ap.add_argument("--freeze-stage5", action="store_true", help="train conv_head+GeM+BN only (ablation)")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    rng = random.Random(args.seed)
    torch.set_num_threads(args.threads)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    cache = Path(args.cache)
    aug = np.load(cache / "train_aug_trunk.npy", mmap_mode="r")
    aug_rows = np.load(cache / "train_aug_rows.npy")
    ev = np.load(cache / "eval_trunk.npy", mmap_mode="r")

    allowed = set(splits["train"])
    if args.hemlock_only:
        allowed = {t for t in allowed if t.startswith("PRU-")}
    # identities = training trees that actually have cached samples
    train_trees = sorted({recs[r].tree_id for r in aug_rows} & allowed)
    tmap = {t: i for i, t in enumerate(train_trees)}
    keep = np.array([recs[r].tree_id in tmap for r in aug_rows])
    aug_idx = np.nonzero(keep)[0]
    labels = np.array([tmap[recs[aug_rows[i]].tree_id] for i in aug_idx])
    counts = [c for _, c in sorted(Counter(labels.tolist()).items())]
    print(f"train identities={len(train_trees)} samples={len(aug_idx)}", flush=True)

    val_rows = np.array([i for i, r in enumerate(recs) if r.tree_id in set(splits["val"]) and r.species == "tsuga_canadensis"])
    val_labels = np.array([recs[i].tree_id for i in val_rows])

    meta = json.loads((cache / "meta.json").read_text()) if (cache / "meta.json").exists() else {}
    backbone = meta.get("backbone", "efficientnetv2_rw_m")
    tail = Tail(backbone, train_stage5=not args.freeze_stage5, img_size=meta.get("size"),
                split=meta.get("split", "trunk"))
    loss_fn = build_loss(args.loss, tail.dim, len(train_trees), class_counts=counts, s=args.s,
                         m_max=args.m_max, k=args.subcenters)
    bb_params, head_params = tail.param_groups()
    groups = [
        {"params": bb_params, "lr": args.lr_backbone},
        {"params": head_params + list(loss_fn.parameters()), "lr": args.lr_head},
    ]
    opt = torch.optim.Adam([g for g in groups if g["params"]])
    n_batches = len(aug_idx) // (args.p * args.k)
    total = args.epochs * n_batches
    warm = max(1, n_batches // 2)
    base = [g["lr"] for g in opt.param_groups]

    def set_lr(step):
        f = (step + 1) / warm if step < warm else 0.5 * (1 + np.cos(np.pi * (step - warm) / max(1, total - warm)))
        for g, b in zip(opt.param_groups, base):
            g["lr"] = b * f

    def val_score():
        e = embed(tail, ev, val_rows)
        return retrieval_metrics(e, val_labels)

    history = []
    m0 = val_score()
    history.append({"epoch": 0, **m0})
    print("epoch 0 val", m0, flush=True)
    best, best_state = m0["mAP"], copy.deepcopy(tail.state_dict())
    step = 0
    t0 = time.time()
    for ep in range(1, args.epochs + 1):
        tail.train()
        losses = []
        for bidx in pk_batches(labels, args.p, args.k, rng):
            set_lr(step)
            rows = aug_idx[bidx]
            order = np.argsort(rows)  # sorted reads from the memmap
            x = torch.from_numpy(aug[rows[order]].astype(np.float32))
            y = torch.from_numpy(labels[bidx][order]).long()
            loss = loss_fn(tail(x), y)
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(float(loss.detach()))
            step += 1
        m = val_score()
        history.append({"epoch": ep, "loss": float(np.mean(losses)), "seconds": time.time() - t0, **m})
        print(f"epoch {ep} loss {np.mean(losses):.3f} val {m} {time.time() - t0:.0f}s", flush=True)
        if m["mAP"] > best:
            best, best_state = m["mAP"], copy.deepcopy(tail.state_dict())
    tail.load_state_dict(best_state)
    torch.save({"tail": best_state, "args": vars(args), "backbone": backbone, "split": tail.split,
                "train_trees": train_trees},
               out / "tail.pt")
    emb = embed(tail, ev, np.arange(len(recs)))
    np.save(out / "embeddings.npy", emb.astype(np.float32))
    (out / "history.json").write_text(json.dumps(history, indent=2))
    print("best val mAP", best)


if __name__ == "__main__":
    main()
