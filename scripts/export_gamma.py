"""Export Model Gamma (the RTX 3060 BarkNet ViT-S/14 448 px checkpoint) to ONNX, weights unchanged.

The checkpoint is the GitHub release asset ``vits_448_best.pt`` of release ``barknet-rtx3060``. Its
sha256 is checked before anything else; the network is rebuilt from the config saved inside it and
loaded with strict key matching, in eval mode, and exported as-is:

    images (N, 3, 448, 448) ImageNet-normalised -> embedding (N, 256), L2-normalised

The app's GammaRuntime does the evaluation preprocessing the checkpoint was validated with
(short side to 640, five 448 px crops, mean of the crop embeddings). See
docs/results/model_comparison/README.md for the reproduction of the reported numbers.

    python scripts/export_gamma.py path/to/vits_448_best.pt   # writes models/gamma/gamma.onnx + gamma.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

SHA256 = "5dfff6e501a3"  # prefix; the full digest is written to gamma.json
RELEASE = "https://github.com/ekaagar-chawla-19/Congressional-App-Challenge-2026/releases/tag/barknet-rtx3060"


def build(checkpoint: str):
    import timm
    import torch

    ck = torch.load(checkpoint, map_location="cpu", weights_only=False)
    cfg = ck["config"]
    size = cfg["train"]["img_size"]
    backbone = timm.create_model(cfg["model"]["backbone"], pretrained=False, num_classes=0, img_size=size)
    neck = torch.nn.Sequential(torch.nn.Linear(768, cfg["model"]["embed_dim"], bias=False),
                               torch.nn.BatchNorm1d(cfg["model"]["embed_dim"]))
    sd = ck["model"]
    backbone.load_state_dict({k[9:]: v for k, v in sd.items() if k.startswith("backbone.")}, strict=True)
    neck.load_state_dict({k[5:]: v for k, v in sd.items() if k.startswith("neck.")}, strict=True)

    class Gamma(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone, self.neck = backbone, neck

        def forward(self, x):
            t = self.backbone.forward_features(x)  # (N, 1 + patches, 384), final norm applied
            f = torch.cat([t[:, 0], t[:, 1:].mean(1)], 1)  # cls_mean pooling, as trained
            return torch.nn.functional.normalize(self.neck(f), dim=1)

    return Gamma().eval(), cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--out", default="models/gamma")
    args = ap.parse_args()
    import onnxruntime as ort
    import torch

    digest = hashlib.sha256(Path(args.checkpoint).read_bytes()).hexdigest()
    if not digest.startswith(SHA256):
        raise SystemExit(f"checkpoint sha256 {digest[:12]} is not the released vits_448_best.pt ({SHA256})")
    net, cfg = build(args.checkpoint)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    x = torch.randn(5, 3, 448, 448)
    with torch.no_grad():
        ref = net(x).numpy()
        torch.onnx.export(net, x, out / "gamma.onnx", input_names=["images"], output_names=["embedding"],
                          dynamic_axes={"images": {0: "n"}, "embedding": {0: "n"}}, opset_version=17, dynamo=False)
    got = ort.InferenceSession(str(out / "gamma.onnx"), providers=["CPUExecutionProvider"]).run(
        None, {"images": x.numpy()})[0]
    diff = float(np.abs(ref - got).max())
    if diff > 1e-4:
        raise SystemExit(f"ONNX output differs from PyTorch by {diff}")
    meta = {"model_key": "gamma", "name": "Model Gamma", "image_size": int(cfg["train"]["img_size"]),
            "resize_short_side": int(cfg.get("eval", {}).get("resize", 640)), "crops": "five",
            "embedding_dim": int(cfg["model"]["embed_dim"]), "species_labels": [],
            "version": "gamma-vits448-barknet-rtx3060", "backbone": cfg["model"]["backbone"],
            "pooling": cfg["model"]["pooling"],
            "preprocessing": "RGB, resize short side to 640, five 448 px crops (centre + corners), /255, "
                             "ImageNet mean/std; embedding = L2-normalised mean of the crop embeddings",
            "source_checkpoint": {"file": "vits_448_best.pt", "sha256": digest, "release": RELEASE,
                                  "weights_modified": False},
            "onnx_max_abs_diff_vs_pytorch": diff}
    (out / "gamma.json").write_text(json.dumps(meta, indent=1))
    print(f"wrote {out / 'gamma.onnx'} ({(out / 'gamma.onnx').stat().st_size / 1e6:.1f} MB), max diff {diff:.2e}")


if __name__ == "__main__":
    main()
