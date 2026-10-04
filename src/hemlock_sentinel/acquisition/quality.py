"""Cheap, explainable per-view image-quality checks run before any network.

Each check returns a reason the UI can show ("Too blurry — hold steady").
Thresholds are config values. The blur and texture defaults come from
scripts/calibrate_quality.py on 200 BarkNet training images vs. Gaussian-
blurred copies (sigma=3 px at 512 px): Laplacian variance 1st pct 74 (sharp)
vs 99th pct 8.3 (blurred) -> threshold 25 (geometric mean); edge density 1st
pct 0.089 vs 99th pct 0.041 -> 0.06. Exposure limits sit outside the 1st/99th
percentiles of real images (mean luma 41..154, clipped fraction <= 0.08).
Results: runs/quality_calibration.json, docs/experiments.md E-quality.

Checks: blur (variance of Laplacian), exposure (fraction of clipped pixels and
mean luminance), low texture (sky / lens covered / no trunk in frame), and
duplicate views (cosine of the view's embedding to the previous views, done in
the pipeline because it needs the embedding). Species-level "is a tree
visible" is handled by the species gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class QualityThresholds:
    min_laplacian_var: float = 25.0
    max_clipped_fraction: float = 0.25
    min_mean_luma: float = 35.0
    max_mean_luma: float = 225.0
    min_edge_density: float = 0.06
    max_duplicate_cosine: float = 0.985
    analysis_side: int = 512


@dataclass
class QualityReport:
    ok: bool
    metrics: dict[str, float] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    weight: float = 1.0  # used for quality-weighted multi-view aggregation


def assess(rgb: np.ndarray, th: QualityThresholds = QualityThresholds()) -> QualityReport:
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = g.shape
    s = th.analysis_side / max(h, w)
    if s < 1:  # analyse at a fixed scale so thresholds do not depend on camera resolution
        g = cv2.resize(g, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    lap = float(cv2.Laplacian(g, cv2.CV_64F).var())
    clipped = float(((g <= 3) | (g >= 252)).mean())
    luma = float(g.mean())
    edges = float((cv2.Canny(g, 50, 150) > 0).mean())
    m = {"laplacian_var": lap, "clipped_fraction": clipped, "mean_luma": luma, "edge_density": edges}
    problems = []
    if lap < th.min_laplacian_var:
        problems.append("blurry: hold the device steady and tap to focus")
    if clipped > th.max_clipped_fraction or luma > th.max_mean_luma:
        problems.append("over-exposed: avoid pointing at the sun / bright sky")
    if luma < th.min_mean_luma:
        problems.append("too dark: move to better light or use the torch")
    if edges < th.min_edge_density:
        problems.append("no tree structure visible: frame the trunk or branches")
    # Soft weight in [0.25, 1]: sharper views count more in the aggregate.
    weight = float(np.clip(np.log1p(lap) / np.log1p(4 * th.min_laplacian_var), 0.25, 1.0))
    return QualityReport(not problems, m, problems, weight)
