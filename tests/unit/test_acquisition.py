import cv2
import numpy as np

from hemlock_sentinel.acquisition.interfaces import Camera, DepthProvider, GPS, Storage
from hemlock_sentinel.acquisition.mocks import (ArrayCamera, FixedGPS, LocalFileStorage, NoDepth, SimulatedDepth,
                                                TrunkModel)
from hemlock_sentinel.acquisition.privacy import blur_faces
from hemlock_sentinel.acquisition.protocol import GUIDED_VIEWS, MIN_VIEWS
from hemlock_sentinel.acquisition.quality import assess
from hemlock_sentinel.preprocessing import resize_short_center_crop, to_network_input


def test_mocks_satisfy_protocols(tmp_path):
    assert isinstance(ArrayCamera([np.zeros((4, 4, 3), np.uint8)]), Camera)
    assert isinstance(NoDepth(), DepthProvider)
    assert isinstance(SimulatedDepth(TrunkModel.random(0)), DepthProvider)
    assert isinstance(FixedGPS(34.5, -84.0), GPS)
    assert isinstance(LocalFileStorage(tmp_path), Storage)


def test_storage_is_content_addressed(tmp_path):
    s = LocalFileStorage(tmp_path)
    k1 = s.put(b"abc", ".jpg")
    k2 = s.put(b"abc", ".jpg")
    assert k1 == k2 and s.get(k1) == b"abc"
    assert len(list(tmp_path.rglob("*.jpg"))) == 1


def test_quality_accepts_sharp_bark(bark):
    r = assess(bark(0))
    assert r.ok, r.problems


def test_quality_rejects_blur(bark):
    blurred = cv2.GaussianBlur(bark(0), (0, 0), 8)
    r = assess(blurred)
    assert not r.ok and any("blurry" in p for p in r.problems)


def test_quality_rejects_dark_and_overexposed(bark):
    assert any("dark" in p for p in assess((bark(0) * 0.1).astype(np.uint8)).problems)
    assert any("over-exposed" in p for p in assess(np.full((300, 300, 3), 255, np.uint8)).problems)


def test_quality_rejects_featureless(bark):
    sky = np.full((400, 300, 3), (120, 160, 210), np.uint8)
    assert any("no tree structure" in p for p in assess(sky).problems)


def test_quality_weight_prefers_sharper(bark):
    sharp = assess(bark(0)).weight
    soft = assess(cv2.GaussianBlur(bark(0), (0, 0), 1.5)).weight
    assert sharp >= soft


def test_preprocessing_shape_and_normalisation(bark):
    x = to_network_input(bark(1, 500, 300), 64)
    assert x.shape == (3, 64, 64) and x.dtype == np.float32
    assert abs(float(x.mean())) < 3
    c = resize_short_center_crop(np.zeros((100, 50, 3), np.uint8), 32)
    assert c.shape == (32, 32, 3)


def test_preprocessing_deterministic(bark):
    img = bark(2)
    assert np.array_equal(to_network_input(img, 96), to_network_input(img, 96))


def test_protocol_has_guided_views():
    assert 3 <= MIN_VIEWS <= len(GUIDED_VIEWS) <= 5
    assert GUIDED_VIEWS[0].identity_view and GUIDED_VIEWS[0].required


def test_next_view_order_and_extra_trunk_views():
    from hemlock_sentinel.acquisition.protocol import next_view

    assert next_view(set()).key == "trunk_north"
    assert next_view({"trunk_north", "trunk_right", "trunk_right2"}).key == "branching"
    nv = next_view({"trunk_north", "trunk_right", "trunk_right2"}, need_identity=True)
    assert nv.key == "trunk_right3" and nv.identity_view
    allk = {"trunk_north", "trunk_right", "trunk_right2", "trunk_right3", "trunk_north_high", "trunk_low_close"}
    assert next_view(allk, need_identity=True) is None
    assert next_view(allk - {"trunk_low_close"}, need_identity=True).key == "trunk_low_close"


def test_face_blur_noop_on_bark(bark):
    img = bark(3)
    out, n = blur_faces(img)
    assert n == 0 and out is img


def test_simulated_depth_is_valid():
    d = SimulatedDepth(TrunkModel.random(1), seed=0).capture_depth()
    valid = d.depth_m[d.depth_m > 0]
    assert valid.size > 100 and 1.0 < np.median(valid) < 2.0


def test_face_is_detected_and_blurred():
    # NASA astronaut portrait (public domain; distributed with scikit-image)
    from pathlib import Path

    img = cv2.cvtColor(cv2.imread(str(Path(__file__).parents[1] / "data" / "astronaut_public_domain_256.jpg")),
                       cv2.COLOR_BGR2RGB)
    out, n = blur_faces(img)
    assert n == 1
    from hemlock_sentinel.acquisition.privacy import detect_faces

    assert detect_faces(out) == []  # blurred face is no longer detectable


def test_heading_check_requires_rotation():
    from hemlock_sentinel.acquisition.quality import heading_problem

    assert heading_problem("trunk_right", 10.0, {"trunk_north": 0.0}) is not None   # did not move
    assert heading_problem("trunk_right", 95.0, {"trunk_north": 0.0}) is None       # quarter-turn
    assert heading_problem("trunk_right", 355.0, {"trunk_north": 5.0}) is not None  # wraps at 360
    assert heading_problem("trunk_right", None, {"trunk_north": 0.0}) is None       # no compass
    assert heading_problem("branching", 0.0, {"trunk_north": 0.0}) is None          # not a rotation view


def test_reduced_jpeg_decode_keeps_min_side_and_orientation(bark):
    import io

    from PIL import Image

    from hemlock_sentinel.preprocessing import decode_image

    big = cv2.resize(bark(5), (1600, 2400))
    buf = io.BytesIO()
    Image.fromarray(big).save(buf, "JPEG", quality=90)
    full = decode_image(buf.getvalue(), None)
    small = decode_image(buf.getvalue(), 640)
    assert full.shape == (2400, 1600, 3)
    assert min(small.shape[:2]) >= 640 and small.shape[0] > small.shape[1]  # portrait kept
    assert small.shape[0] < full.shape[0]
    x_full, x_small = to_network_input(full, 96), to_network_input(small, 96)
    assert np.corrcoef(x_full.ravel(), x_small.ravel())[0, 1] > 0.98


def test_quality_report_fields_are_not_shifted(bark):
    # Regression: adding QualityReport.warnings shifted the positional `weight` into it.
    r = assess(bark(0))
    assert isinstance(r.weight, float) and 0.25 <= r.weight <= 1.0
    assert r.warnings == [] and r.problems == []
