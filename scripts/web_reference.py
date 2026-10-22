"""Reference outputs for the browser speed test (web/speedtest): what the Python server computes for one photo.

The browser runs the same ONNX files with its own preprocessing (JavaScript). Comparing its embeddings with these
(cosine similarity) shows whether the phone would make the same decisions as the server.

    python scripts/web_reference.py            # writes web/speedtest/sample.jpg (if missing) and reference.json
    python scripts/web_reference.py photo.jpg  # reference for another photo (printed, not saved)

The sample is a drawn bark-like texture (no dataset photo is published with the site).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hemlock_sentinel.pipeline.runtime import GammaRuntime, OnnxRuntime  # noqa: E402
from hemlock_sentinel.preprocessing import decode_image, to_network_input  # noqa: E402
from hemlock_sentinel.species.inference import softmax  # noqa: E402

OUT = ROOT / "web" / "speedtest"


def make_sample(path: Path, w: int = 1200, h: int = 1600, seed: int = 7) -> None:
    """Vertical ridges with cracks and lichen spots, like trunk bark at chest height."""
    from PIL import Image

    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    warp = sum(np.sin(y / p + rng.uniform(0, 6.3)) * a for p, a in ((90, 18), (37, 7), (13, 2)))
    ridges = np.sin((x + warp) / rng.uniform(9, 12)) + 0.5 * np.sin((x + 1.7 * warp) / 4.3)
    noise = rng.normal(0, 1, (h // 8 + 1, w // 8 + 1)).repeat(8, 0).repeat(8, 1)[:h, :w]
    v = 0.55 + 0.18 * ridges + 0.08 * noise
    rgb = np.stack([v * 0.62, v * 0.50, v * 0.40], -1)
    for _ in range(40):  # lichen
        cy, cx, r = rng.integers(0, h), rng.integers(0, w), rng.integers(6, 30)
        m = (y - cy) ** 2 + (x - cx) ** 2 < r ** 2
        rgb[m] = rgb[m] * 0.4 + np.array([0.55, 0.6, 0.5]) * 0.6
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(path, quality=90)


def reference(photo: Path) -> dict:
    rgb = decode_image(photo.read_bytes())
    delta = OnnxRuntime(ROOT / "models" / "production" / "hemlock.onnx")
    emb, logits = delta.run(to_network_input(rgb, delta.input_size)[None])
    p = softmax(logits[0])
    gamma = GammaRuntime(ROOT / "models" / "gamma" / "gamma.onnx")
    g, _ = gamma.embed_rgb(rgb)
    unit = lambda v: (v / np.linalg.norm(v)).round(6).tolist()  # noqa: E731
    return {"photo": photo.name, "decoded_size": [int(rgb.shape[1]), int(rgb.shape[0])],
            "delta": {"embedding": unit(emb[0]), "hemlock_probability": round(float(p[0]), 6),
                      "species_labels": delta.species_labels},
            "gamma": {"embedding": unit(g)}}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        r = reference(Path(sys.argv[1]))
        print(json.dumps({**r, "delta": {**r["delta"], "embedding": r["delta"]["embedding"][:4]},
                          "gamma": {"embedding": r["gamma"]["embedding"][:4]}}, indent=1))
    else:
        sample = OUT / "sample.jpg"
        if not sample.exists():
            make_sample(sample)
        (OUT / "reference.json").write_text(json.dumps(reference(sample)))
        print("wrote", OUT / "reference.json")
