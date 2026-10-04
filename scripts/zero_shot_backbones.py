"""Zero-shot backbone comparison on hemlock val/test trees (no fine-tuning).

Each backbone: frozen pretrained weights -> GeM(p=3) over its last feature map
(CLS-free patch tokens for ViTs) -> L2 normalisation. This isolates "how
individual-discriminative are the pretrained features" — a cheap,
controlled comparison. Fine-tuning every alternative is out of this
project's CPU budget (docs/experiments.md says so explicitly).

Usage: python scripts/zero_shot_backbones.py --out runs/results/zero_shot.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch

from hemlock_sentinel.evaluation.benchmarks import build_observations, closed_set_topk, genuine_impostor, run_open_set
from hemlock_sentinel.evaluation.metrics import retrieval_metrics, roc_auc
from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.preprocessing import to_network_input
from hemlock_sentinel.reid.backbone import Backbone
from hemlock_sentinel.reid.gem import GeM

BACKBONES = {
    # name: (timm id, input size)
    "efficientnetv2_rw_m (ImageNet-1k)": ("efficientnetv2_rw_m.agc_in1k", 320),
    "convnext_tiny (IN-22k->1k)": ("convnext_tiny.fb_in22k_ft_in1k", 320),
    "swin_tiny (IN-1k)": ("swin_tiny_patch4_window7_224.ms_in1k", 224),
    "dinov2_vits14 (LVD-142M)": ("vit_small_patch14_dinov2.lvd142m", 322),
}


def load_miewid() -> torch.nn.Module:
    """MiewID-msv3 weights (wildlife re-ID) loaded into our identical architecture."""
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    from hemlock_sentinel.reid.embedding import ReIDConfig, ReIDNet

    sd = load_file(hf_hub_download("conservationxlabs/miewid-msv3", "model.safetensors"))
    net = ReIDNet(ReIDConfig(pretrained=False))
    mapped = {}
    for k, v in sd.items():
        if k.startswith("backbone.global_pool."):  # MiewID-msv3 keeps GeM as the timm global_pool
            mapped["pool." + k[len("backbone.global_pool."):]] = v
        elif k.startswith("backbone."):
            mapped["backbone.model." + k[len("backbone."):]] = v
        elif k.startswith("pooling."):
            mapped["pool." + k[len("pooling."):]] = v
        elif k.startswith("bn."):
            mapped[k] = v
    missing, unexpected = net.load_state_dict(mapped, strict=False)
    missing = [m for m in missing if not m.startswith("species_head")]
    if missing:
        raise RuntimeError(f"MiewID weights missing keys: {missing[:5]}")
    return net.eval()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", default="runs/results/zero_shot.json")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--only", default=None, help="substring: run only matching models (merges into --out)")
    args = ap.parse_args()
    torch.set_num_threads(args.threads)
    recs = read_manifest(Path(args.data) / "manifest.csv")
    splits = json.loads((Path(args.data) / "splits.json").read_text())
    ev = set(splits["val"]) | set(splits["test"])
    rows = [i for i, r in enumerate(recs) if r.tree_id in ev and r.species == "tsuga_canadensis"]
    imgs = {}
    for i in rows:
        bgr = cv2.imread(recs[i].path, cv2.IMREAD_REDUCED_COLOR_2)
        imgs[i] = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    prev = json.loads(Path(args.out).read_text()) if Path(args.out).exists() else {}
    results = {**prev, "protocol": "zero-shot, frozen weights, hemlock val+test trees (never trained on), "
                           "views=3, enrolled 0.5, 20 repeats"}
    models = list(BACKBONES.items()) + [("MiewID-msv3 (wildlife re-ID, EfficientNetV2-M)", ("miewid", 320))]
    for name, (tid, size) in models:
        if args.only and args.only not in name:
            continue
        t0 = time.time()
        if tid == "miewid":
            net = load_miewid()
            fn = net.embed  # its trained GeM + BN
        else:
            kw = {"img_size": size} if "dinov2" in tid else {}
            bb = Backbone(tid, pretrained=True, **kw).eval()
            gem = GeM(3.0, learnable=False)
            fn = lambda x, bb=bb, gem=gem: gem(bb(x))  # noqa: E731
        embs = {}
        with torch.inference_mode():
            for s in range(0, len(rows), 16):
                chunk = rows[s:s + 16]
                x = torch.from_numpy(np.stack([to_network_input(imgs[i], size) for i in chunk]))
                for i, e in zip(chunk, fn(x).float().numpy()):
                    embs[i] = e
        dt = (time.time() - t0) / len(rows)
        emb_of = {recs[i].path: embs[i] for i in rows}
        out = {"sec_per_image_incl_load": round(dt, 4), "input_size": size}
        for split in ("val", "test"):
            ids = set(splits[split])
            r_ = [i for i in rows if recs[i].tree_id in ids]
            out[f"image_retrieval_{split}"] = retrieval_metrics(np.stack([embs[i] for i in r_]),
                                                                np.array([recs[i].tree_id for i in r_]))
            obs = build_observations(recs, ids, "tsuga_canadensis", 3, seed=1 if split == "val" else 2)
            qs = run_open_set(obs, emb_of, repeats=args.repeats, seed=100 if split == "val" else 200)
            g, im = genuine_impostor(qs)
            out[f"observation_{split}"] = closed_set_topk(qs) | {"roc_auc": round(roc_auc(g, im), 4)}
        results[name] = out
        print(name, json.dumps(out), flush=True)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
