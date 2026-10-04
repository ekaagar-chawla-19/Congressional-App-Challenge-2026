"""Threshold selection and score calibration from validation data.

No threshold in this project is hand-set: every decision threshold is produced
by one of these functions from held-out validation pairs and saved to a JSON
calibration file next to the model (configs/ or runs/).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np


def threshold_at_fmr(impostor_scores: np.ndarray, target_fmr: float) -> float:
    """Smallest threshold t such that P(impostor >= t) <= target_fmr.

    "Accept" means score >= t. With n impostor scores we can only resolve FMR
    to 1/n; if target_fmr < 1/n the returned threshold is just above the
    largest impostor score (empirical FMR = 0) — callers should report n.
    """
    s = np.sort(np.asarray(impostor_scores, dtype=np.float64))[::-1]
    if len(s) == 0:
        raise ValueError("need impostor scores")
    allowed = int(np.floor(target_fmr * len(s)))
    if allowed >= len(s):
        return float(s[-1])
    # accept at most `allowed` impostors: threshold strictly above s[allowed]
    return float(np.nextafter(s[allowed], np.inf))


def threshold_for_gallery(pair_impostor_scores: np.ndarray, n_gallery: int, target_fmr: float) -> float:
    """Gallery-size-aware threshold.

    A new tree is falsely matched if ANY of the n_gallery wrong trees scores >= t.
    Treating wrong-tree scores as independent draws from the per-pair impostor
    distribution F, P(false match) = 1 - (1 - F(t))^n. So we need a per-pair
    exceedance of 1 - (1 - target)^(1/n), which shrinks as the gallery grows.
    Fitted on validation per-pair scores and re-evaluated for the deployed
    gallery size (the app recomputes it as the gallery grows).
    """
    if n_gallery < 1:
        raise ValueError("n_gallery >= 1")
    per_pair = 1.0 - (1.0 - target_fmr) ** (1.0 / n_gallery)
    return threshold_at_fmr(pair_impostor_scores, per_pair)


def threshold_max_f1(genuine: np.ndarray, impostor: np.ndarray) -> float:
    g = np.asarray(genuine, dtype=np.float64)
    i = np.asarray(impostor, dtype=np.float64)
    cands = np.unique(np.concatenate([g, i]))
    best_t, best_f1 = float(cands[0]), -1.0
    for t in cands:
        tp = (g >= t).sum()
        fp = (i >= t).sum()
        fn = (g < t).sum()
        f1 = 2 * tp / max(2 * tp + fp + fn, 1)
        if f1 > best_f1:
            best_f1, best_t = f1, float(t)
    return best_t


@dataclass
class LogisticCalibrator:
    """P(same tree | features) via logistic regression; numpy-only at inference."""

    feature_names: list[str]
    coef: list[float] = field(default_factory=list)
    intercept: float = 0.0
    mean: list[float] = field(default_factory=list)
    scale: list[float] = field(default_factory=list)

    def fit(self, X: np.ndarray, y: np.ndarray, C: float = 1.0) -> "LogisticCalibrator":
        from sklearn.linear_model import LogisticRegression

        X = np.asarray(X, dtype=np.float64)
        mu, sd = X.mean(0), X.std(0) + 1e-9
        lr = LogisticRegression(C=C, max_iter=1000).fit((X - mu) / sd, y)
        self.coef = lr.coef_[0].tolist()
        self.intercept = float(lr.intercept_[0])
        self.mean, self.scale = mu.tolist(), sd.tolist()
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, dtype=np.float64))
        z = ((X - np.asarray(self.mean)) / np.asarray(self.scale)) @ np.asarray(self.coef) + self.intercept
        return 1.0 / (1.0 + np.exp(-z))


@dataclass
class Calibration:
    """Everything the decision logic needs; produced by scripts/calibrate.py."""

    species_threshold: float = 0.5  # min P(supported species) before any ID is assigned
    match_threshold: float = 0.5  # on fused P(same tree)
    global_threshold: float = 0.5  # fallback when only the global score is available
    target_fmr: float = 0.01
    view_contradiction_margin: float = 0.0  # per-view score gap that flags a contradiction
    # A single view scoring >= this against some gallery tree is strong evidence on
    # its own (calibrated at target_fmr on per-view impostor scores). If the
    # observation as a whole does not match but such a view exists, the capture is
    # mixed/ambiguous and must not silently create a new tree. None = disabled.
    view_match_threshold: float | None = None
    # Embedding cosine above which a new view is treated as a re-shoot of an earlier
    # view (scripts/calibrate_duplicate.py). Model-specific, so it lives here.
    duplicate_cosine: float | None = None
    fusers: dict[str, LogisticCalibrator] = field(default_factory=dict)  # key: "+".join(features)
    provenance: dict = field(default_factory=dict)  # split, n pairs, date — for honesty

    def save(self, path: str | Path) -> None:
        d = asdict(self)
        Path(path).write_text(json.dumps(d, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Calibration":
        d = json.loads(Path(path).read_text())
        d["fusers"] = {k: LogisticCalibrator(**v) for k, v in d.get("fusers", {}).items()}
        return cls(**d)
