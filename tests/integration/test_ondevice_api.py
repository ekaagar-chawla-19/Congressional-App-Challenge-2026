"""Endpoints the phone needs to run the model itself: model files, calibration, forest gallery."""

import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from hemlock_sentinel.api.accounts import Accounts
from hemlock_sentinel.api.server import DEFAULT_CALIBRATION, DEFAULT_MODEL, create_api
from tests.helpers import tree_view
from tests.integration.test_accounts_forests import make_accounts, signup

V = "/api/v1"


def _jpeg(img):
    return cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


def test_gallery_matches_stored_embeddings_and_is_private(tmp_path):
    acc = make_accounts(tmp_path)
    c = TestClient(create_api(accounts=acc))
    h = signup(c, "g@example.org")
    f = c.post(f"{V}/forests", json={"name": "G"}, headers=h).json()
    hf = {**h, "X-Forest-Id": str(f["forest_id"])}
    assert c.get(f"{V}/gallery", headers=hf).json()["observations"] == []
    for seed in (1, 2):
        files = [("images", (f"{v}.jpg", _jpeg(tree_view(seed, v)), "image/jpeg")) for v in range(3)]
        c.post(f"{V}/identify", files=files, headers=hf)
    g = c.get(f"{V}/gallery", headers=hf).json()
    assert g["tree_ids"] == ["H-001", "H-002"] and g["species"] == "tsuga_canadensis" and g["embedding_dim"] == 128
    repo = acc.pipeline(acc.forest(1, f["forest_id"])).repo
    _, oids, emb = repo.gallery("tsuga_canadensis")
    for o, e in zip(g["observations"], emb):
        v = np.frombuffer(base64.b64decode(o["embedding_b64"]), "<f4")
        assert v.shape == (128,) and abs(np.linalg.norm(v) - 1) < 1e-5
        assert float(v @ (e / np.linalg.norm(e))) > 0.9999
    other = signup(c, "o@example.org")
    assert c.get(f"{V}/gallery", headers={**other, "X-Forest-Id": str(f["forest_id"])}).status_code == 404
    # mock model: nothing to download
    assert c.get(f"{V}/model").json()["on_device"] is None
    assert c.get(f"{V}/model/files/hemlock.onnx").json()["error"]["code"] == "no_model_files"


@pytest.mark.skipif(not DEFAULT_MODEL.exists(), reason="production model not present")
def test_model_files_for_phone(tmp_path):
    from hemlock_sentinel.app.server import load_model

    rt, cal, _ = load_model(str(DEFAULT_MODEL), str(DEFAULT_CALIBRATION))
    c = TestClient(create_api(accounts=Accounts(tmp_path, rt, cal)))
    od = c.get(f"{V}/model").json()["on_device"]
    assert od["onnx_bytes"] == DEFAULT_MODEL.stat().st_size and len(od["onnx_sha256"]) == 64
    meta = c.get(od["meta_url"]).json()
    assert meta["image_size"] == 322 and meta["embedding_dim"] == 384
    cj = c.get(od["calibration_url"]).json()
    assert cj["match_threshold"] == pytest.approx(cal.match_threshold) and "global+gap+agreement" in cj["fusers"]
    r = c.get(od["onnx_url"])
    assert r.status_code == 200 and len(r.content) == od["onnx_bytes"] and r.headers["etag"].strip('"') in od["onnx_sha256"]
    assert c.get(f"{V}/model/files/secret.txt").status_code == 404
    js = c.get("/ondevice.js")
    assert js.status_code == 200 and "class OnDeviceModel" in js.text
    w = c.get("/ort/ort-wasm-simd-threaded.wasm")
    assert w.status_code == 200 and w.headers["content-type"] == "application/wasm"
    assert c.get("/ort/../server.py").status_code == 404
