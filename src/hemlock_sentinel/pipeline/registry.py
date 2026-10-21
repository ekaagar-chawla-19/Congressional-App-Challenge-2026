"""The re-ID models the app can choose between, loaded once per process.

* delta: our production model (models/production/hemlock.onnx): DINOv2 ViT-S/14 at 322 px with a species
  head (only Eastern hemlocks get a tree ID).
* gamma: the RTX 3060 BarkNet checkpoint (models/gamma/gamma.onnx, weights unchanged): DINOv2 ViT-S/14 at
  448 px, five crops per photo, no species head.

Each has its own calibration (decision thresholds) and its own embedding space, so trees are fingerprinted
once per model (model_embeddings). The numbers quoted to users come from
docs/results/model_comparison/README.md (2,371 real iNaturalist hemlocks).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..reid.calibration import Calibration

DEFAULT_MODEL = "delta"

TEXT = {
    "delta": {
        "name": "Model delta",
        "tagline": "Faster, checks the species first",
        "description": "DINOv2 ViT-S/14 at 322 px, fine-tuned on BarkNet. Checks that the bark is an Eastern "
                       "hemlock before matching. About 0.5 s per photo. On 2,371 real phone photos of hemlocks it "
                       "picked the right tree first 35% of the time, and its species check accepted 14% of them.",
        "real_photo_top1": 0.35,
        "speed": "fast",
    },
    "gamma": {
        "name": "Model gamma",
        "tagline": "Best match accuracy on real photos",
        "description": "DINOv2 ViT-S/14 at 448 px (RTX 3060 BarkNet run), five crops per photo. Does not check "
                       "the species: it assumes the tree is an Eastern hemlock. About 2 s per photo. On 2,371 "
                       "real phone photos of hemlocks it picked the right tree first 53% of the time.",
        "real_photo_top1": 0.53,
        "speed": "slower",
    },
}


@dataclass
class ModelSpec:
    key: str
    runtime: object
    cal: Calibration
    demo: bool = False
    text: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.text.get("name", self.key)

    @property
    def version(self) -> str:
        return getattr(self.runtime, "version", "unknown")

    @property
    def checks_species(self) -> bool:
        return bool(getattr(self.runtime, "species_labels", None))


def spec(key: str, runtime, cal: Calibration, demo: bool = False) -> ModelSpec:
    t = dict(TEXT.get(key, {"name": key, "tagline": "", "description": ""}))
    if demo:
        t["tagline"] = "Demo stand-in (mock model)"
        t["description"] = "The server runs without model weights (--demo): results are meaningless."
    return ModelSpec(key, runtime, cal, demo, t)


def load_models(delta_model: str | None, delta_cal: str | None, gamma_model: str | None = None,
                gamma_cal: str | None = None) -> dict[str, ModelSpec]:
    """Both real models (delta required, gamma when its files exist), or two mock models when delta_model is
    None (demo mode)."""
    from ..app.server import load_model
    from .runtime import GammaRuntime, MockRuntime

    if delta_model is None:
        rt, cal, _ = load_model(None, None)
        g = MockRuntime(input_size=96, embedding_dim=128, species_labels=[], seed=1)
        gcal = Calibration(species_threshold=0.0, global_threshold=0.8, match_threshold=0.5,
                           view_contradiction_margin=0.05, view_match_threshold=0.5,
                           provenance={"note": "DEMO calibration for the mock model; not validated"})
        return {"delta": spec("delta", rt, cal, True), "gamma": spec("gamma", g, gcal, True)}
    rt, cal, _ = load_model(delta_model, delta_cal)
    out = {"delta": spec("delta", rt, cal)}
    if gamma_model and Path(gamma_model).exists():
        if not gamma_cal or not Path(gamma_cal).exists():
            raise SystemExit(f"model gamma needs its calibration: {gamma_cal}")
        out["gamma"] = spec("gamma", GammaRuntime(gamma_model), Calibration.load(gamma_cal))
    return out
