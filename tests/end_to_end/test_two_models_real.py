"""Both real models (delta: models/production, gamma: models/gamma) through the app's guided-capture API.

Skipped unless both ONNX files and the BarkNet manifest exist (runs/data, see README "Reproduce").
Only TEST-split hemlocks: delta never trained on them, gamma never saw any hemlock.

Checks what the app relies on: the chosen model really runs (different versions, embedding sizes and
timings), a tree registered with one model is recognised by the other, gamma never invents a species,
black frames are rejected before any model, and ESP32 data reaches the diagnosis with either model.
"""

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from hemlock_sentinel.api.server import DELTA_CALIBRATION, DELTA_MODEL, GAMMA_CALIBRATION, GAMMA_MODEL

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "runs/data"
V = "/api/v1"

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(not (DELTA_MODEL.exists() and GAMMA_MODEL.exists() and (DATA / "manifest.csv").exists()),
                                 reason="model files / BarkNet manifest not available")]


def _hemlocks():
    from hemlock_sentinel.evaluation.splits import read_manifest

    test = set(json.loads((DATA / "splits.json").read_text())["test"])
    by = {}
    for r in read_manifest(DATA / "manifest.csv"):
        if r.tree_id in test and r.species == "tsuga_canadensis" and Path(r.path).exists():
            by.setdefault(r.tree_id, []).append(r.path)
    return {k: sorted(v) for k, v in sorted(by.items()) if len(v) >= 12}


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    from fastapi.testclient import TestClient

    from hemlock_sentinel.api.accounts import Accounts
    from hemlock_sentinel.api.server import create_api
    from hemlock_sentinel.pipeline.registry import load_models

    acc = Accounts(tmp_path_factory.mktemp("api"), models=load_models(str(DELTA_MODEL), str(DELTA_CALIBRATION),
                                                                     str(GAMMA_MODEL), str(GAMMA_CALIBRATION)))
    c = TestClient(create_api(accounts=acc))
    tok = c.post(f"{V}/auth/register", json={"email": "e2e@example.org", "password": "correct horse",
                                            "name": "E2E"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    fid = c.post(f"{V}/forests", json={"name": "BarkNet test stand"}, headers=h).json()["forest_id"]
    return c, {**h, "X-Forest-Id": str(fid)}, acc


def scan(c, h, model, photos, **body):
    cap = c.post(f"{V}/captures", json={"model": model}, headers=h).json()
    t = time.perf_counter()
    for p in photos:
        r = c.post(f"{V}/captures/{cap['capture_id']}/views", files={"image": ("v.jpg", Path(p).read_bytes(), "image/jpeg")},
                   headers=h).json()
        assert r["view"]["accepted"], r
    r = c.post(f"{V}/captures/{cap['capture_id']}/identify", json={"force_commit": True, **body}, headers=h).json()
    r["_seconds"] = time.perf_counter() - t
    return r


def test_models_report_real_weights(app):
    c, _, _ = app
    m = {x["key"]: x for x in c.get(f"{V}/models").json()["models"]}
    assert m["delta"]["version"].startswith("hemlock-dino") and m["delta"]["embedding_dim"] == 384
    assert m["gamma"]["version"].startswith("gamma-vits448") and m["gamma"]["embedding_dim"] == 256
    assert m["gamma"]["image_size"] == 448 and not m["gamma"]["checks_species"] and not m["gamma"]["demo"]
    meta = json.loads(GAMMA_MODEL.with_suffix(".json").read_text())
    assert meta["source_checkpoint"]["weights_modified"] is False
    assert meta["source_checkpoint"]["sha256"].startswith("5dfff6e501a3")


@pytest.mark.parametrize("enrol,revisit", [("delta", "gamma"), ("gamma", "delta")])
def test_register_with_one_model_recognise_with_the_other(app, enrol, revisit):
    c, h, acc = app
    trees = _hemlocks()
    names = list(trees)[:4] if enrol == "delta" else list(trees)[4:8]
    ids = {}
    for t in names:
        r = scan(c, h, enrol, trees[t][:3])
        assert r["model"] == enrol and r["status"] in ("new", "uncertain", "existing"), r
        if r["status"] != "new":  # a look-alike already in the stand: register it as new for this test
            r["tree_id"] = c.post(f"{V}/observations/{r['observation_id']}/assign", json={"tree_id": "new"},
                                  headers=h).json()["tree_id"]
        ids[t] = r["tree_id"]
    acc.wait_background(timeout=600)
    # The other model's fingerprint of each enrolment, made in the background from the stored photos, must be
    # exactly what that model computes from the same photos directly.
    from hemlock_sentinel.preprocessing import decode_image
    from hemlock_sentinel.reid.multiview import aggregate_mean

    forest = acc.forests(1)[0]
    pipe = acc.pipeline(forest, revisit)
    for t, tid in ids.items():
        oid = pipe.repo.get_observations(tid)[0].observation_id
        stored = pipe.repo.model_embedding(oid, revisit)
        direct = aggregate_mean(np.stack([pipe.embed(decode_image(Path(p).read_bytes()))[0] for p in trees[t][:3]]))
        assert stored is not None and float(stored @ direct) > 0.999, (t, revisit)
    right = wrong = 0
    for t in names:
        half = len(trees[t]) // 2
        r = scan(c, h, revisit, trees[t][half:half + 3])  # other photos of the same tree
        assert r["model"] == revisit
        top = r["candidates"][0]["tree_id"] if r["candidates"] else None
        right += top == ids[t]
        wrong += r["status"] == "existing" and r["tree_id"] != ids[t]
        if revisit == "gamma":
            assert r["species"] is None and r["species_checked"] is False
        else:
            assert r["species_checked"] is True
    # Accuracy itself is the model's: gamma ranks 3-4 of these revisits first, delta (weaker on these trees,
    # docs/results/model_comparison) 1-2. Neither may confirm a wrong tree more than once.
    assert right >= (3 if revisit == "gamma" else 1), (enrol, revisit, right)
    assert wrong <= 1


def test_gamma_does_not_confirm_look_alikes_in_a_new_forest(app, tmp_path):
    """One tree enrolled, other hemlocks scanned: the virtual competitor (gap_floor) keeps gamma from
    calling them the same tree (it did, at ~100% confidence, before gap_floor)."""
    from fastapi.testclient import TestClient

    from hemlock_sentinel.api.accounts import Accounts
    from hemlock_sentinel.api.server import create_api

    _, _, acc0 = app
    acc = Accounts(tmp_path, models=acc0.models)
    c = TestClient(create_api(accounts=acc))
    tok = c.post(f"{V}/auth/register", json={"email": "n@e.org", "password": "correct horse", "name": "N"}).json()
    h = {"Authorization": f"Bearer {tok['token']}"}
    fid = c.post(f"{V}/forests", json={"name": "new"}, headers=h).json()["forest_id"]
    h["X-Forest-Id"] = str(fid)
    trees = list(_hemlocks().values())
    assert scan(c, h, "gamma", trees[0][:3])["status"] == "new"
    false = sum(scan(c, h, "gamma", t[:3])["status"] == "existing" for t in trees[1:5])
    assert false == 0


def test_black_frames_rejected_before_either_model(app):
    c, h, _ = app
    black = cv2.imencode(".jpg", np.zeros((960, 720, 3), np.uint8))[1].tobytes()
    for model in ("delta", "gamma"):
        cap = c.post(f"{V}/captures", json={"model": model}, headers=h).json()
        r = c.post(f"{V}/captures/{cap['capture_id']}/views", files={"image": ("b.jpg", black, "image/jpeg")},
                   headers=h).json()
        assert r["view"]["accepted"] is False and any("dark" in p for p in r["view"]["problems"]), r


def test_esp32_data_reaches_the_diagnosis_with_real_models(app):
    from hemlock_sentinel.esp32.reading import parse_reading

    c, h, _ = app
    trees = _hemlocks()
    t = list(trees)[9]
    reading = parse_reading(json.dumps({"v": 1, "device": "HS-ESP32-1A2B", "soil_moisture_pct": 8, "air_temp_c": 32,
                                        "humidity_pct": 35, "light_lux": 26000}))
    for model in ("gamma", "delta"):
        r = scan(c, h, model, trees[t][3 * (model == "delta"):3 * (model == "delta") + 3],
                 sensors=reading["sensors"], signs=["drought_browning"])
        f = {x["condition"]: x for x in r["findings"]}
        assert f["drought_stress"]["level"] == "likely", r["findings"]
        o = c.get(f"{V}/observations/{r['observation_id']}", headers=h).json()
        assert o["sensors"]["soil_moisture_pct"] == 8
