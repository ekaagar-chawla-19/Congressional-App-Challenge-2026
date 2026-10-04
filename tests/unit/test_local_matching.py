import cv2
import numpy as np
import pytest

from hemlock_sentinel.acquisition.mocks import SimulatedDepth, TrunkModel
from hemlock_sentinel.reid.local_matching import (Intrinsics, KeypointMatcher, fit_circle, profile_similarity,
                                                  trunk_profile_from_depth)


def _warp(img, angle=4, scale=1.03, shift=(6, -4)):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    M[:, 2] += shift
    return cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)


def test_keypoint_matcher_same_surface_vs_different(bark):
    m = KeypointMatcher()
    a = m.extract(bark(10))
    a2 = m.extract(_warp(bark(10)))
    b = m.extract(bark(11))
    same, diff = m.inliers(a, a2), m.inliers(a, b)
    assert same > 3 * max(diff, 5), (same, diff)
    assert a.descriptors.dtype == np.uint8 and a.descriptors.shape[1] == 128


def test_keypoint_score_empty():
    m = KeypointMatcher()
    blank = m.extract(np.zeros((100, 100, 3), np.uint8))
    assert len(blank.descriptors) == 0
    assert m.score([blank], [blank]) == 0.0
    assert m.score([], []) == 0.0


def test_fit_circle_exact():
    t = np.linspace(-1.0, 1.0, 50)  # only a front arc is visible
    x, z = 0.3 + 0.2 * np.sin(t), 2.0 - 0.2 * np.cos(t)
    cx, cz, r = fit_circle(x, z)
    assert (cx, cz, r) == pytest.approx((0.3, 2.0, 0.2), abs=1e-6)


def _profile(seed, noise_b, offset=0.0, rng_seed=0):
    sim = SimulatedDepth(TrunkModel.random(seed), noise_a=0.0, noise_b=noise_b, height_offset_m=offset, seed=rng_seed)
    d = sim.capture_depth()
    return trunk_profile_from_depth(d.depth_m, Intrinsics(d.fx, d.fy, d.cx, d.cy))


def test_trunk_profile_recovers_diameter_noise_free():
    tm = TrunkModel.random(3)
    p = _profile(3, 0.0)
    ok = ~np.isnan(p.diameters)
    assert ok.sum() > 5
    # heights are relative to the lowest visible point; compare the median diameter
    true = tm.diameter(np.linspace(0.3, 2.0, 50))
    assert np.nanmedian(p.diameters) == pytest.approx(np.median(true), rel=0.15)


def test_profile_similarity_same_tree_higher_than_other_tree():
    a = _profile(5, 0.0005, rng_seed=1)
    a2 = _profile(5, 0.0005, offset=0.05, rng_seed=2)
    b = _profile(6, 0.0005, rng_seed=3)
    s_same, s_diff = profile_similarity(a, a2, tol_m=0.02), profile_similarity(a, b, tol_m=0.02)
    assert s_same > s_diff


def test_profile_similarity_no_overlap_is_nan():
    from hemlock_sentinel.reid.local_matching import TrunkProfile

    assert np.isnan(profile_similarity(TrunkProfile(np.zeros(0), np.zeros(0)), _profile(1, 0.0)))
