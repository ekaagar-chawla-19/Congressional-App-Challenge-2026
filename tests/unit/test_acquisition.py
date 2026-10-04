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
