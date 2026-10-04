"""Assemble the deployable model and export it to ONNX.

1. Full ReIDNet = pretrained EfficientNetV2-M trunk (frozen stages 0-4) +
   fine-tuned tail (stage 5, conv_head, GeM, BN) + species head (Linear on the
   L2-normalised embedding).
2. Save a Torch checkpoint (TorchRuntime) and an ONNX graph + JSON sidecar
   (OnnxRuntime, the edge default).
3. Verify numerical parity Torch vs ONNX Runtime on real images.

Usage:
    python scripts/export_model.py --tail runs/reid/subcenter/tail.pt --species runs/species/subcenter/species_head.npz \
        --out runs/export/hemlock
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from hemlock_sentinel.reid.embedding import ReIDConfig, ReIDNet

TRUNK_STAGES = 5


def assemble(tail_path: str, species_path: str, image_size: int) -> tuple[ReIDNet, list[str]]:
    sp = np.load(species_path)
    labels = [str(x) for x in sp["labels"]]
    net = ReIDNet(ReIDConfig(pretrained=True, image_size=image_size, n_species=len(labels)))
    tail = torch.load(tail_path, map_location="cpu", weights_only=False)["tail"]
    sd = net.state_dict()
    mapped = {}
    for k, v in tail.items():
        if k.startswith("stage5."):
            i, rest = k[len("stage5."):].split(".", 1)
            mapped[f"backbone.model.blocks.{TRUNK_STAGES + int(i)}.{rest}"] = v
        elif k.startswith("conv_head.") or k.startswith("bn2."):
            mapped["backbone.model." + k] = v
        elif k.startswith("head.pool."):
            mapped["pool." + k[len("head.pool."):]] = v
        elif k.startswith("head.bn."):
            mapped["bn." + k[len("head.bn."):]] = v
        else:
            raise KeyError(k)
    unknown = set(mapped) - set(sd)
    if unknown:
        raise KeyError(f"unmapped tail keys: {sorted(unknown)[:5]}")
    sd.update(mapped)
    sd["species_head.weight"] = torch.from_numpy(sp["W"])
    sd["species_head.bias"] = torch.from_numpy(sp["b"])
    net.load_state_dict(sd)
    return net.eval(), labels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail", required=True)
    ap.add_argument("--species", required=True)
    ap.add_argument("--out", default="runs/export/hemlock")
    ap.add_argument("--image-size", type=int, default=320)
    ap.add_argument("--version", default=time.strftime("hemlock-%Y%m%d"))
    ap.add_argument("--check-images", nargs="*", default=[])
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    net, labels = assemble(args.tail, args.species, args.image_size)
    cfg = {"backbone": net.cfg.backbone, "image_size": args.image_size, "gem_p": 3.0, "n_species": len(labels)}
    torch.save({"config": cfg, "state_dict": net.state_dict(), "species_labels": labels, "version": args.version},
               out.with_suffix(".pt"))

    x = torch.randn(2, 3, args.image_size, args.image_size)
    torch.onnx.export(net, x, str(out.with_suffix(".onnx")), input_names=["images"],
                      output_names=["embedding", "species_logits"],
                      dynamic_axes={"images": {0: "n"}, "embedding": {0: "n"}, "species_logits": {0: "n"}},
                      opset_version=17, dynamo=False)
    meta = {"image_size": args.image_size, "embedding_dim": net.embedding_dim, "species_labels": labels,
            "version": args.version, "backbone": net.cfg.backbone,
            "preprocessing": "RGB, resize short side to image_size (INTER_AREA), centre crop, /255, ImageNet mean/std"}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2))

    import onnxruntime as ort

    from hemlock_sentinel.preprocessing import decode_image, to_network_input

    sess = ort.InferenceSession(str(out.with_suffix(".onnx")), providers=["CPUExecutionProvider"])
    batch = [to_network_input(decode_image(Path(p).read_bytes()), args.image_size) for p in args.check_images]
    xs = np.stack(batch) if batch else x.numpy()
    with torch.no_grad():
        te, tl = net(torch.from_numpy(xs))
    oe, ol = sess.run(None, {"images": xs.astype(np.float32)})
    te, tl = te.numpy(), tl.numpy()
    cos = (te * oe).sum(1) / (np.linalg.norm(te, axis=1) * np.linalg.norm(oe, axis=1))
    parity = {"max_abs_diff_embedding": float(np.abs(te - oe).max()), "min_cosine_torch_vs_onnx": float(cos.min()),
              "max_abs_diff_species_logits": float(np.abs(tl - ol).max()), "n_images": len(xs)}
    print(json.dumps(parity, indent=1))
    (out.parent / "parity.json").write_text(json.dumps(parity, indent=2))
    assert parity["min_cosine_torch_vs_onnx"] > 0.9999, "ONNX export diverges from Torch"


if __name__ == "__main__":
    main()
