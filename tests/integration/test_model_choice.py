"""Choosing the re-ID model (delta / gamma) per capture, with mock models (fast, no weights).

* both models are listed, a capture runs the chosen model and says so;
* a tree registered with one model is recognised by the other (photos fingerprinted by every model);
* gamma has no species check: no species is invented, the result says it was not checked;
* the ESP32 reading and checklist feed the disease findings the same way for both, and more data can be
  added to the visit and the tree afterwards;
* deleting a tree removes every model's fingerprints; old single-model databases keep working.
"""

import json
import time
import uuid

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from hemlock_sentinel.api.accounts import Accounts
from hemlock_sentinel.api.demo_seed import DEMO_EMAIL, seed_demo
from hemlock_sentinel.api.server import create_api
from hemlock_sentinel.database.models import ObservationRecord
from hemlock_sentinel.esp32.reading import parse_reading
from hemlock_sentinel.pipeline.registry import spec
from hemlock_sentinel.pipeline.runtime import MockRuntime
from hemlock_sentinel.reid.calibration import Calibration
from tests.helpers import species_fn_factory, tree_view

V = "/api/v1"
# What the ESP32 node sends over BLE (firmware/esp32_sensors): a dry, hot, bright site.
ESP32_JSON = json.dumps({"v": 1, "device": "HS-ESP32-1A2B", "soil_moisture_pct": 9.5, "air_temp_c": 31.2,
                         "humidity_pct": 38, "light_lux": 24000, "soil_raw": 3020, "uptime_s": 812})


def _cal():
    return Calibration(species_threshold=0.6, global_threshold=0.8, match_threshold=0.5,
                       view_contradiction_margin=0.05, view_match_threshold=0.4)


def make_accounts(tmp_path):
    delta = MockRuntime(input_size=64, embedding_dim=128, species_fn=species_fn_factory())
    gamma = MockRuntime(input_size=64, embedding_dim=96, species_labels=[], seed=1)
    gamma.version = "gamma-mock"
    return Accounts(tmp_path / "data", models={"delta": spec("delta", delta, _cal()),
                                               "gamma": spec("gamma", gamma, _cal())})


@pytest.fixture
def env(tmp_path):
    acc = make_accounts(tmp_path)
    c = TestClient(create_api(accounts=acc))
    r = c.post(f"{V}/auth/register", json={"email": "crew@example.org", "password": "correct horse", "name": "Crew"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    f = c.post(f"{V}/forests", json={"name": "Test stand", "lat": 34.75, "lon": -84.0}, headers=h).json()
    return c, {**h, "X-Forest-Id": str(f["forest_id"])}, acc, acc.forest(1, f["forest_id"])


def _jpeg(img):
    return cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


def guided(c, h, tree, model, jitter=0, **body):
    """The app's flow: start a capture with a model, add 3 trunk photos, identify."""
    cap = c.post(f"{V}/captures", json={"model": model} if model else None, headers=h)
    assert cap.status_code == 201, cap.text
    cid = cap.json()["capture_id"]
    for v in range(3):
        r = c.post(f"{V}/captures/{cid}/views", files={"image": ("v.jpg", _jpeg(tree_view(tree, v, jitter)), "image/jpeg")},
                   headers=h)
        assert r.status_code == 200 and r.json()["view"]["accepted"], r.text
    r = c.post(f"{V}/captures/{cid}/identify", json={"force_commit": True, **body}, headers=h)
    assert r.status_code == 200, r.text
    return cap.json(), r.json()


def test_models_listed_and_capture_runs_the_chosen_one(env):
    c, h, _, _ = env
    m = c.get(f"{V}/models").json()
    assert m["default"] == "delta" and [x["key"] for x in m["models"]] == ["delta", "gamma"]
    by = {x["key"]: x for x in m["models"]}
    assert by["delta"]["name"] == "Model Delta" and by["delta"]["checks_species"] is True
    assert by["gamma"]["name"] == "Model Gamma" and by["gamma"]["checks_species"] is False
    assert by["gamma"]["embedding_dim"] == 96 and by["delta"]["embedding_dim"] == 128
    assert c.get(f"{V}/health").json()["models"] == ["delta", "gamma"]
    cap, r = guided(c, h, 1, "gamma")
    assert cap["model"] == "gamma" and cap["model_name"] == "Model Gamma"
    assert r["model"] == "gamma" and r["status"] == "new" and r["tree_id"] == "H-001"
    cap, r = guided(c, h, 2, None)  # no model given: the default
    assert cap["model"] == "delta" and r["model"] == "delta"
    bad = c.post(f"{V}/captures", json={"model": "omega"}, headers=h)
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unknown_model"
    assert c.get(f"{V}/model?model=gamma").json()["embedding_dim"] == 96


def test_species_is_not_invented_for_gamma(env):
    c, h, acc, f = env
    _, d = guided(c, h, 3, "delta")
    assert d["species_checked"] is True and d["species"]["label"] == "tsuga_canadensis"
    _, g = guided(c, h, 4, "gamma")
    assert g["species_checked"] is False and g["species"] is None
    assert "does not check the species" in g["message"]
    o = acc.pipeline(f).repo.get_observation(g["observation_id"])
    assert o.species == "tsuga_canadensis" and o.species_confidence is None  # assumed, not measured
    assert o.model_version == "gamma-mock"


@pytest.mark.parametrize("first,second", [("delta", "gamma"), ("gamma", "delta")])
def test_tree_registered_with_one_model_is_recognised_by_the_other(env, first, second):
    c, h, acc, f = env
    _, a = guided(c, h, 7, first)
    assert a["status"] == "new"
    acc.wait_background()  # the other model fingerprints the stored photos in the background
    repo = acc.pipeline(f).repo
    assert repo.models_for(a["observation_id"]) == ["delta", "gamma"]
    _, b = guided(c, h, 7, second, jitter=1)  # revisit, other model
    assert b["model"] == second and b["status"] == "existing" and b["tree_id"] == a["tree_id"]
    _, other = guided(c, h, 8, second)
    assert other["status"] == "new" and other["tree_id"] != a["tree_id"]


def test_identify_catches_up_even_if_the_background_job_has_not_run(env):
    c, h, acc, f = env
    _, a = guided(c, h, 9, "delta")
    acc.wait_background()
    repo = acc.pipeline(f).repo
    repo.query("DELETE FROM model_embeddings WHERE model='gamma'")  # as if the background job never ran
    acc.pipeline(f, "gamma").index.invalidate()
    _, b = guided(c, h, 9, "gamma", jitter=2)
    assert b["status"] == "existing" and b["tree_id"] == a["tree_id"]


def test_one_shot_identify_takes_a_model_field(env):
    c, h, _, _ = env
    files = [("images", (f"{v}.jpg", _jpeg(tree_view(11, v)), "image/jpeg")) for v in range(3)]
    r = c.post(f"{V}/identify", files=files, data={"model": "gamma"}, headers=h).json()
    assert r["model"] == "gamma" and r["status"] == "new"
    r = c.post(f"{V}/identify", files=files, data={"model": "nope"}, headers=h).json()
    assert r["error"]["code"] == "unknown_model"
    r = c.post(f"{V}/identify", files=files, headers={**h, "X-Model": "gamma"}).json()
    assert r["model"] == "gamma" and r["status"] == "existing"


@pytest.mark.parametrize("model", ["delta", "gamma"])
def test_esp32_reading_and_checklist_drive_the_diagnosis_with_either_model(env, model):
    """The phone parses the ESP32 reading and sends it with the identify call; findings come back. Then the
    crew adds more data: a corrected reading, more signs, a sensor-only revisit, and a later photo visit."""
    c, h, acc, f = env
    reading = parse_reading(ESP32_JSON)
    assert reading["device"] == "HS-ESP32-1A2B" and reading["sensors"]["soil_moisture_pct"] == 9.5
    _, r = guided(c, h, 21, model, sensors=reading["sensors"], signs=["drought_browning", "needle_loss"], severity=1)
    assert r["model"] == model and r["observation_id"]
    found = {x["condition"]: x for x in r["findings"]}
    assert found["drought_stress"]["level"] == "likely", r["findings"]  # dry soil + browning
    assert found["hwa"]["level"] != "likely"
    oid, tid = r["observation_id"], r["tree_id"]

    # more data on the same visit: wool found on a twig, and a second ESP32 reading after rain
    o = c.put(f"{V}/observations/{oid}/signs", json={"signs": ["drought_browning", "needle_loss", "hwa_wool"]},
              headers=h).json()
    assert any(x["condition"] == "hwa" and x["level"] == "likely" for x in o["findings"]), o["findings"]
    wet = parse_reading(json.dumps({"v": 1, "device": "HS-ESP32-1A2B", "soil_moisture_pct": 41, "air_temp_c": 19,
                                    "humidity_pct": 81, "light_lux": 3000}))
    o = c.put(f"{V}/observations/{oid}/sensors", json=wet["sensors"], headers=h).json()
    assert o["sensors"]["soil_moisture_pct"] == 41
    wet_found = {x["condition"]: x for x in o["findings"]}
    assert wet_found["drought_stress"]["likelihood"] < found["drought_stress"]["likelihood"]  # reading matters

    # a sensor-only revisit (ESP32 at the tree, no photos), then a photo revisit with the same model
    v = c.post(f"{V}/trees/{tid}/visits", json={"sensors": reading["sensors"], "signs": ["hwa_wool"]}, headers=h)
    assert v.status_code == 201 and v.json()["has_photos"] is False
    acc.wait_background()
    _, again = guided(c, h, 21, model, jitter=3, sensors=wet["sensors"], signs=["hwa_wool"])
    assert again["status"] == "existing" and again["tree_id"] == tid
    t = c.get(f"{V}/trees/{tid}", headers=h).json()
    assert t["observation_count"] == 3 and t["latest_sensors"]["soil_moisture_pct"] == 41
    assert len(t["observations"]) == 3


def test_delete_tree_removes_every_models_fingerprints(env):
    c, h, acc, f = env
    _, a = guided(c, h, 31, "gamma")
    acc.wait_background()
    repo = acc.pipeline(f).repo
    assert len(repo.models_for(a["observation_id"])) == 2
    assert c.delete(f"{V}/trees/{a['tree_id']}", headers=h).status_code == 204
    assert repo.query("SELECT COUNT(*) FROM model_embeddings")[0][0] == 0
    _, b = guided(c, h, 31, "delta", jitter=1)
    assert b["status"] == "new"  # the deleted tree is not matched by either model


def test_database_from_before_model_choice_still_matches(tmp_path):
    """Observations stored with only observations.aggregated_embedding (the old schema) are adopted as
    Model Delta's fingerprints, and gamma embeds their photos when first used."""
    acc = make_accounts(tmp_path)
    c = TestClient(create_api(accounts=acc))
    tok = c.post(f"{V}/auth/register", json={"email": "a@b.org", "password": "correct horse", "name": "A"}).json()
    h = {"Authorization": f"Bearer {tok['token']}"}
    fid = c.post(f"{V}/forests", json={"name": "Old"}, headers=h).json()["forest_id"]
    h["X-Forest-Id"] = str(fid)
    _, a = guided(c, h, 41, "delta")
    acc.wait_background()
    repo = acc.pipeline(acc.forest(1, fid)).repo
    repo.query("DELETE FROM model_embeddings")  # what an old database looks like
    for p in acc.pipelines(acc.forest(1, fid)).values():
        p.index.invalidate()
    _, b = guided(c, h, 41, "delta", jitter=1)
    assert b["status"] == "existing" and b["tree_id"] == a["tree_id"]
    _, g = guided(c, h, 41, "gamma", jitter=2)
    assert g["status"] == "existing" and g["tree_id"] == a["tree_id"]


def test_demo_forests_have_placeholder_fingerprints_for_every_model(tmp_path):
    acc = make_accounts(tmp_path)
    user = seed_demo(acc, now=time.time())
    assert user.email == DEMO_EMAIL
    for f in acc.forests(user.user_id):
        repo = acc.pipeline(f).repo
        n = repo.query("SELECT COUNT(*) FROM observations")[0][0]
        for key in ("delta", "gamma"):
            assert repo.query("SELECT COUNT(*) FROM model_embeddings WHERE model=?", (key,))[0][0] == n
    seed_demo(acc)  # idempotent
    f = acc.forests(user.user_id)[0]
    repo = acc.pipeline(f).repo
    assert repo.query("SELECT COUNT(*) FROM model_embeddings WHERE model='gamma'")[0][0] == \
        repo.query("SELECT COUNT(*) FROM observations")[0][0]


def test_species_check_endpoint_uses_the_model_with_a_species_head(env):
    c, h, _, _ = env
    r = c.post(f"{V}/species-check", files={"image": ("v.jpg", _jpeg(tree_view(51, 0)), "image/jpeg")},
               headers={**h, "X-Model": "gamma"})
    assert r.status_code == 200 and r.json()["verdict"] == "hemlock", r.text


def test_single_mode_rejects_a_model_it_does_not_run(tmp_path):
    from tests.helpers import build

    c = TestClient(create_api(build(tmp_path)))
    assert [m["key"] for m in c.get(f"{V}/models").json()["models"]] == ["delta"]
    assert c.post(f"{V}/captures", json={"model": "gamma"}).json()["error"]["code"] == "unknown_model"
    assert c.post(f"{V}/captures", json={"model": "delta"}).status_code == 201


def test_stored_observation_without_photos_is_not_backfilled(env):
    """Placeholder / sensor-only visits have no photos: nothing to embed, and no error."""
    c, h, acc, f = env
    repo = acc.pipeline(f).repo
    tid = repo.create_tree("tsuga_canadensis", "H")
    repo.add_observation(ObservationRecord(uuid.uuid4().hex, tid, time.time(), "new", "tsuga_canadensis", 0.9, None,
                                           np.ones(128, np.float32), model_version="x"))
    assert acc.sync(f, "gamma") == 0
    _, r = guided(c, h, 61, "gamma")
    assert r["status"] == "new"


def test_a_later_moist_reading_supersedes_an_earlier_dry_one(env):
    """Tree status shows each condition's latest assessment: a wet ESP32 reading must clear 'drought likely'."""
    c, h, _, _ = env
    dry = parse_reading(ESP32_JSON)["sensors"]
    _, r = guided(c, h, 71, "gamma", sensors=dry, signs=["drought_browning"])
    tid = r["tree_id"]
    cur = {f["condition"]: f for f in c.get(f"{V}/trees/{tid}", headers=h).json()["current_conditions"]}
    assert cur["drought_stress"]["level"] == "likely"
    wet = {"soil_moisture_pct": 44.0, "air_temp_c": 18.0, "humidity_pct": 83.0, "light_lux": 2100.0}
    v = c.post(f"{V}/trees/{tid}/visits", json={"sensors": wet}, headers=h).json()
    assert {f["condition"]: f for f in v["findings"]}["drought_stress"]["level"] == "low"
    cur = {f["condition"]: f for f in c.get(f"{V}/trees/{tid}", headers=h).json()["current_conditions"]}
    assert cur["drought_stress"]["level"] == "low" and "not dry" in cur["drought_stress"]["evidence"][0]
    c.post(f"{V}/trees/{tid}/visits", json={"sensors": dry}, headers=h)  # dry again: back to likely
    cur = {f["condition"]: f for f in c.get(f"{V}/trees/{tid}", headers=h).json()["current_conditions"]}
    assert cur["drought_stress"]["level"] in ("likely", "possible")
