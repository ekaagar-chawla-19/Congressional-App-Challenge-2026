"""Local matching: (1) bark keypoint matching on RGB, (2) trunk structure from depth.

Why these two, and why no extra neural network
----------------------------------------------
* Bark surfaces are individual: Robert et al. (2020, arXiv:1912.03221)
  re-identify the *same bark surface* with keypoint descriptors + geometric
  verification. Their learned DeepBark descriptor beat SIFT, but SIFT-family
  matching is the dependency-free baseline we can run on a Pi; we use RootSIFT
  (Arandjelović & Zisserman, CVPR 2012) + RANSAC and only re-rank the top-k
  global candidates, so cost is bounded by k, not by gallery size.
* Tree architecture is individual: Yrttimaa et al. (Forestry 2025) identified
  80% of 65 Scots pines from TLS stem profiles and branch-origin patterns
  (100% when >=10 branch origins were re-observed). Consumer depth cannot
  resolve branch origins like TLS can, so the defensible part to transfer is
  the stem diameter profile (diameter vs height), matched with a tolerance.
  Validated here only on simulated depth; see docs/experiments.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


# --------------------------------------------------------------------------
# RGB keypoints
# --------------------------------------------------------------------------
@dataclass
class LocalFeatures:
    keypoints: np.ndarray  # (N, 2) float32, pixel coords at the working resolution
    descriptors: np.ndarray  # (N, 128) uint8 quantised RootSIFT

    def nbytes(self) -> int:
        return self.keypoints.nbytes + self.descriptors.nbytes

    def to_npz_dict(self, prefix: str = "") -> dict:
        return {f"{prefix}kp": self.keypoints, f"{prefix}desc": self.descriptors}


class KeypointMatcher:
    def __init__(self, max_side: int = 640, n_features: int = 500, ratio: float = 0.8,
                 ransac_px: float = 6.0, min_matches: int = 8):
        self.max_side = max_side
        self.n_features = n_features
        self.ratio = ratio
        self.ransac_px = ransac_px
        self.min_matches = min_matches
        self._sift = cv2.SIFT_create(nfeatures=n_features)

    def extract(self, image: np.ndarray) -> LocalFeatures:
        g = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        h, w = g.shape
        s = self.max_side / max(h, w)
        if s < 1:
            g = cv2.resize(g, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_AREA)
        kps, desc = self._sift.detectAndCompute(g, None)
        if desc is None or len(kps) == 0:
            return LocalFeatures(np.zeros((0, 2), np.float32), np.zeros((0, 128), np.uint8))
        desc = desc / np.maximum(desc.sum(1, keepdims=True), 1e-7)  # RootSIFT: L1 then sqrt
        desc = np.sqrt(desc)
        q = np.clip(np.round(desc * 255.0), 0, 255).astype(np.uint8)
        pts = np.array([k.pt for k in kps], dtype=np.float32)
        return LocalFeatures(pts, q)

    def inliers(self, a: LocalFeatures, b: LocalFeatures) -> int:
        if len(a.descriptors) < 2 or len(b.descriptors) < 2:
            return 0
        da = a.descriptors.astype(np.float32) / 255.0
        db = b.descriptors.astype(np.float32) / 255.0
        knn = cv2.BFMatcher(cv2.NORM_L2).knnMatch(da, db, k=2)
        good = [m[0] for m in knn if len(m) == 2 and m[0].distance < self.ratio * m[1].distance]
        if len(good) < self.min_matches:
            return 0
        src = a.keypoints[[m.queryIdx for m in good]]
        dst = b.keypoints[[m.trainIdx for m in good]]
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, self.ransac_px)
        return int(mask.sum()) if mask is not None else 0

    def score(self, query_views: list[LocalFeatures], gallery_views: list[LocalFeatures]) -> float:
        """Mean over query views of the best inlier count against any gallery view, as log1p."""
        if not query_views or not gallery_views:
            return 0.0
        best = [max(self.inliers(q, g) for g in gallery_views) for q in query_views]
        return float(np.log1p(np.mean(best)))


# --------------------------------------------------------------------------
# Depth: trunk diameter profile
# --------------------------------------------------------------------------
@dataclass
class Intrinsics:
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass
class TrunkProfile:
    heights: np.ndarray  # (S,) metres above the lowest visible trunk point
    diameters: np.ndarray  # (S,) metres, NaN where the slice fit failed

    @property
    def dbh(self) -> float:
        """Diameter at ~1.3 m above the lowest visible point (NaN if not observed)."""
        ok = ~np.isnan(self.diameters)
        if not ok.any():
            return float("nan")
        i = np.argmin(np.abs(self.heights - 1.3))
        return float(self.diameters[i]) if ok[i] and abs(self.heights[i] - 1.3) < 0.15 else float("nan")


def fit_circle(x: np.ndarray, z: np.ndarray) -> tuple[float, float, float]:
    """Algebraic (Kåsa) least-squares circle fit; returns (cx, cz, r)."""
    A = np.c_[2 * x, 2 * z, np.ones_like(x)]
    b = x * x + z * z
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cz, c = sol
    r2 = c + cx * cx + cz * cz
    return float(cx), float(cz), float(np.sqrt(max(r2, 0.0)))


def trunk_profile_from_depth(depth: np.ndarray, K: Intrinsics, slice_m: float = 0.1,
                             band_m: float = 0.6, min_points: int = 30) -> TrunkProfile:
    """Estimate stem diameters per height slice from a single depth map.

    Assumes the trunk is roughly centred and the camera roughly upright (the
    capture UI asks for this). Trunk pixels: valid depth within ``band_m`` of
    the median depth of the central image column strip. Each horizontal slice
    of trunk points is circle-fitted in the x-z plane (only the front arc is
    visible, which Kåsa handles but with a bias that cancels when comparing
    two profiles from the same sensor type).
    """
    d = np.asarray(depth, dtype=np.float32)
    h, w = d.shape
    strip = d[:, w // 2 - max(w // 40, 1): w // 2 + max(w // 40, 1)]
    valid_strip = strip[strip > 0]
    if valid_strip.size == 0:
        return TrunkProfile(np.zeros(0), np.zeros(0))
    z0 = float(np.median(valid_strip))
    vs, us = np.nonzero((d > 0) & (np.abs(d - z0) < band_m))
    z = d[vs, us]
    x = (us - K.cx) * z / K.fx
    y = -(vs - K.cy) * z / K.fy  # up is positive
    # keep the connected trunk column: points whose x is near the strip's x
    xc = float(np.median(x[np.abs(us - w // 2) < max(w // 40, 1)])) if np.any(np.abs(us - w // 2) < max(w // 40, 1)) else 0.0
    keep = np.abs(x - xc) < band_m
    x, y, z = x[keep], y[keep], z[keep]
    if len(y) < min_points:
        return TrunkProfile(np.zeros(0), np.zeros(0))
    y0 = y.min()
    hs = np.arange(0.0, y.max() - y0 + 1e-9, slice_m)
    diam = np.full(len(hs), np.nan)
    for i, hh in enumerate(hs):
        sel = (y - y0 >= hh) & (y - y0 < hh + slice_m)
        if sel.sum() >= min_points:
            _, _, r = fit_circle(x[sel], z[sel])
            if 0.02 < r < 2.0:
                diam[i] = 2 * r
    return TrunkProfile(hs + slice_m / 2, diam)


def profile_similarity(a: TrunkProfile, b: TrunkProfile, tol_m: float = 0.01,
                       max_shift_m: float = 0.2, min_overlap: int = 5) -> float:
    """Fraction of co-observed heights whose diameters agree within ``tol_m``.

    Yrttimaa et al. matched TLS stem diameters with a 1.0 cm tolerance. The
    lowest visible point differs between captures, so we search a vertical
    shift up to ``max_shift_m`` and keep the best agreement. Returns NaN when
    fewer than ``min_overlap`` slices overlap (no evidence either way).
    """
    if len(a.heights) == 0 or len(b.heights) == 0:
        return float("nan")
    step = float(np.median(np.diff(a.heights))) if len(a.heights) > 1 else 0.1
    best = float("nan")
    for k in range(-int(round(max_shift_m / step)), int(round(max_shift_m / step)) + 1):
        hb = b.heights + k * step
        db = np.interp(a.heights, hb, b.diameters, left=np.nan, right=np.nan)
        ok = ~np.isnan(a.diameters) & ~np.isnan(db)
        if ok.sum() < min_overlap:
            continue
        frac = float((np.abs(a.diameters[ok] - db[ok]) < tol_m).mean())
        if np.isnan(best) or frac > best:
            best = frac
    return best
