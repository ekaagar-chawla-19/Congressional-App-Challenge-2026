"""Species gating with a validated confidence threshold."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .labels import COMMON_NAMES, REID_SUPPORTED, SPECIES


def softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    e = np.exp(x - x.max(axis=axis, keepdims=True))
    return e / e.sum(axis=axis, keepdims=True)


@dataclass
class SpeciesResult:
    species: str  # label or "unknown"
    confidence: float
    probabilities: dict[str, float]
    reid_allowed: bool
    checked: bool = True  # False: the model has no species head; the species is assumed, not measured

    @property
    def common_name(self) -> str:
        return COMMON_NAMES.get(self.species, self.species)


def assumed_hemlock() -> SpeciesResult:
    """For a model without a species head (Model Gamma): the user is scanning hemlocks, nothing was measured."""
    return SpeciesResult("tsuga_canadensis", float("nan"), {}, True, checked=False)


def classify_observation(view_logits: np.ndarray, threshold: float, labels: list[str] = SPECIES,
                         view_weights: np.ndarray | None = None) -> SpeciesResult:
    """Fuse per-view species logits (V, S) by averaging probabilities.

    If the top probability is below ``threshold`` (calibrated on validation so
    that held-out species are rejected, scripts/calibrate.py), the observation is
    "unknown" and no individual ID may be assigned.
    """
    p = softmax(np.atleast_2d(view_logits))
    w = np.ones(len(p)) if view_weights is None else np.asarray(view_weights, dtype=np.float64)
    if w.sum() <= 0:
        w = np.ones(len(p))
    mean = (w[:, None] * p).sum(0) / w.sum()
    i = int(mean.argmax())
    conf = float(mean[i])
    probs = {labels[j]: float(mean[j]) for j in range(len(labels))}
    if conf < threshold:
        return SpeciesResult("unknown", conf, probs, False)
    return SpeciesResult(labels[i], conf, probs, labels[i] in REID_SUPPORTED)
