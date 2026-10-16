"""Visits with photos and/or Pi sensors, health findings, best guess, forest analysis, AI assistant (fake client)."""

import json
from types import SimpleNamespace as NS

import cv2
import pytest
from fastapi.testclient import TestClient

from hemlock_sentinel.api.assistant import Assistant
from hemlock_sentinel.api.server import create_api
from tests.helpers import tree_view
from tests.integration.test_accounts_forests import make_accounts, signup

V = "/api/v1"


def _jpeg(img):
    return cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


class FakeClaude:
    """Scripted stand-in for anthropic.Anthropic(): returns queued responses, records requests."""

    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.requests.append(json.loads(json.dumps(kw, default=lambda o: o.__dict__)))
        return self.responses.pop(0)


def tool_call(name, inp, i="t1"):
    return NS(stop_reason="tool_use", content=[NS(type="thinking", thinking="", signature="s"),
                                               NS(type="tool_use", id=i, name=name, input=inp)])


def text(t):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=t)])


@pytest.fixture
def env(tmp_path):
    fake = FakeClaude([])
    acc = make_accounts(tmp_path)
    c = TestClient(create_api(accounts=acc, assistant=Assistant(client=fake)))
    h = signup(c, "field@example.org")
    f = c.post(f"{V}/forests", json={"name": "Test cove", "lat": 34.8, "lon": -84.1}, headers=h).json()
    return c, {**h, "X-Forest-Id": str(f["forest_id"])}, f, fake


def capture(c, h, seed, jitter=0, **form):
    files = [("images", (f"{v}.jpg", _jpeg(tree_view(seed, v, jitter)), "image/jpeg")) for v in range(3)]
    r = c.post(f"{V}/identify", files=files, data=form, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_visit_data_photos_sensors_and_na(env):
    c, h, _, _ = env
    r = capture(c, h, 1, lat="34.8001", lon="-84.1001", severity="2", signs="hwa_wool,needle_loss",
                soil_moisture_pct="12", air_temp_c="33", humidity_pct="35", light_lux="9000")
    f = {x["condition"]: x for x in r["findings"]}
    assert f["hwa"]["level"] == "likely" and f["drought_stress"]["level"] in ("possible", "likely")
    assert any("VPD" in e for e in f["drought_stress"]["evidence"])
    # second visit: photos only -> sensors N/A
    r2 = capture(c, h, 1, jitter=3)
    assert r2["tree_id"] == "H-001"
    # third visit: Pi reading only, no photos
    v = c.post(f"{V}/trees/H-001/visits", json={"sensors": {"soil_moisture_pct": 30, "air_temp_c": 18}}, headers=h)
    assert v.status_code == 201 and v.json()["has_photos"] is False and v.json()["sensors"]["soil_moisture_pct"] == 30
    assert c.post(f"{V}/trees/H-001/visits", json={}, headers=h).json()["error"]["code"] == "empty_visit"
    t = c.get(f"{V}/trees/H-001", headers=h).json()
    obs = t["observations"]
    assert [o["has_photos"] for o in obs] == [True, True, False]
    assert obs[0]["sensors"]["light_lux"] == 9000 and obs[1]["sensors"] is None and obs[2]["sensors"]["air_temp_c"] == 18
    assert obs[1]["findings"][0]["level"] == "unknown"  # bark photos only: not assessed, never "healthy"
    assert t["latest_sensors"]["soil_moisture_pct"] == 30
    cur = {x["condition"]: x for x in t["current_conditions"]}
    assert cur["hwa"]["level"] == "likely" and t["main_condition"] == "hwa"
    # signs can be edited later; findings follow
    oid = obs[1]["observation_id"]
    o = c.put(f"{V}/observations/{oid}/signs", json={"signs": ["ehs_scale"]}, headers=h).json()
    assert {x["condition"] for x in o["findings"] if x["level"] == "likely"} == {"ehs"}
    assert c.put(f"{V}/observations/{oid}/signs", json={"signs": ["bogus"]}, headers=h).json()["error"]["code"] == \
        "unknown_sign"
    o = c.put(f"{V}/observations/{oid}/sensors", json={"soil_moisture_pct": 5}, headers=h).json()
    assert o["sensors"]["soil_moisture_pct"] == 5
    bad = c.post(f"{V}/identify", headers=h, data={"soil_moisture_pct": "140"},
                 files=[("images", (f"{v}.jpg", _jpeg(tree_view(2, v)), "image/jpeg")) for v in range(3)])
    assert bad.status_code == 422
    g = c.get(f"{V}/health-guide").json()
    assert set(g["conditions"]) == {"hwa", "ehs", "drought_stress"} and "hwa_wool" in g["signs"]


def test_best_guess_offered_and_accepted(env):
    c, h, _, _ = env
    for seed in (50, 51):
        assert capture(c, h, seed)["status"] == "new"
    mixed = [tree_view(50, 0, 3), tree_view(50, 1, 3), tree_view(51, 2, 3)]

    def send(**form):
        files = [("images", (f"{i}.jpg", _jpeg(im), "image/jpeg")) for i, im in enumerate(mixed)]
        return c.post(f"{V}/identify", files=files, data=form, headers=h).json()

    r = send()
    assert r["status"] == "uncertain" and r["action"] == "review" and r["tree_id"] is None
    assert r["best_guess"]["tree_id"] == r["candidates"][0]["tree_id"] and "confident" in r["best_guess"]["note"]
    r = send(accept_best_guess="true")
    assert r["action"] == "done" and r["tree_id"] == r["best_guess"]["tree_id"]
    o = c.get(f"{V}/observations/{r['observation_id']}", headers=h).json()
    assert o["status"] == "best_guess" and o["tree_id"] == r["tree_id"]


def test_forest_analysis_zones_and_area(env):
    c, h, f, _ = env
    # two clusters ~500 m apart: one dry and infested, one healthy
    for i in range(3):
        capture(c, h, 60 + i, lat=f"{34.8 + i * 1e-4}", lon="-84.1", severity="3", signs="hwa_wool,needle_loss",
                soil_moisture_pct="9")
        capture(c, h, 70 + i, lat=f"{34.8045 + i * 1e-4}", lon="-84.1", severity="0", signs="twigs_checked_clean",
                soil_moisture_pct="35")
    a = c.get(f"{V}/forests/{f['forest_id']}/analysis", headers=h).json()
    s = a["summary"]
    assert s["trees"] == 6 and s["most_prominent_condition"] == "hwa" and s["conditions"]["hwa"]["likely"] == 3
    assert s["sensor_means"]["soil_moisture_pct"]["mean"] == 22.0 and s["trees_with_sensor_data"] == 6
    assert s["recommendations"][0]["condition"] == "hwa" and s["general_advice"]
    z = a["zones"]
    assert len(z) == 2 and z[0]["rank"] == 1 and z[0]["most_prominent_condition"] == "hwa"
    assert z[0]["stress_score"] > z[1]["stress_score"] and z[0]["trees"] == 3
    assert a["worst_trees"][0]["severity"] == 3
    area = c.get(f"{V}/analysis", params={"west": -84.11, "south": 34.804, "east": -84.09, "north": 34.806},
                 headers=h).json()
    assert area["summary"]["trees"] == 3 and area["summary"]["severity_counts"]["none"] == 3
    assert c.get(f"{V}/analysis", params={"west": 1, "south": 1, "east": 0, "north": 2}, headers=h).status_code == 400
    m = c.get(f"{V}/map", headers=h).json()
    p = m["features"][0]["properties"]
    assert p["main_condition"] in ("hwa", None) and "stress_score" in p and "latest_sensors" in p


def test_assistant_uses_scoped_tools(env):
    c, h, f, fake = env
    capture(c, h, 80, lat="34.8", lon="-84.1", severity="3", signs="hwa_wool")
    fake.responses += [tool_call("get_forest_zones", {"forest_id": f["forest_id"]}),
                       text("Section #1 is worst: HWA on H-001.")]
    r = c.post(f"{V}/assistant/chat", json={"message": "Where is it worst?", "forest_id": f["forest_id"]},
               headers={"Authorization": h["Authorization"]}).json()
    assert r["reply"].startswith("Section #1") and r["tools_used"][0]["tool"] == "get_forest_zones"
    req = fake.requests[1]
    assert req["model"] == "claude-haiku-5-5" and req["thinking"] == {"type": "adaptive"}
    result = req["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and "H-001" in result["content"]
    assert "[App context: looking at forest" in req["messages"][0]["content"]
    # follow-up continues the same append-only history (thinking blocks kept)
    fake.responses.append(text("Treat with a licensed applicator."))
    r2 = c.post(f"{V}/assistant/chat", json={"message": "What now?", "conversation_id": r["conversation_id"]},
                headers={"Authorization": h["Authorization"]}).json()
    assert r2["conversation_id"] == r["conversation_id"]
    hist = fake.requests[2]["messages"]
    assert len(hist) == 5 and hist[1]["content"][0]["type"] == "thinking"
    # another user's forest is not reachable through the tools
    other = signup(c, "other@example.org")
    fake.responses += [tool_call("get_forest_analysis", {"forest_id": f["forest_id"]}), text("I can't see that.")]
    c.post(f"{V}/assistant/chat", json={"message": "show me"}, headers=other)
    assert "forest_not_found" in fake.requests[-1]["messages"][-1]["content"][0]["content"] or \
        fake.requests[-1]["messages"][-1]["content"][0].get("is_error")


def test_assistant_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    acc = make_accounts(tmp_path)
    c = TestClient(create_api(accounts=acc))
    h = signup(c, "x@example.org")
    r = c.post(f"{V}/assistant/chat", json={"message": "hi"}, headers=h)
    assert r.status_code in (503, 401) and r.json()["error"]["code"] == "assistant_not_configured"


def test_ai_photo_check_of_twig_closeup(env):
    c, h, _, fake = env
    files = [("images", (f"{v}.jpg", _jpeg(tree_view(90, v)), "image/jpeg")) for v in range(3)]
    files.append(("images", ("twig.jpg", _jpeg(tree_view(91, 0)), "image/jpeg")))
    r = c.post(f"{V}/identify", files=files, headers=h,
               data={"view_keys": "trunk_north,trunk_right,trunk_right2,twig_underside"}).json()
    oid = r["observation_id"]
    no_twig = capture(c, h, 92)["observation_id"]
    assert c.post(f"{V}/observations/{no_twig}/inspect", headers=h).json()["error"]["code"] == "no_twig_photos"
    fake.responses.append(text(json.dumps({"usable": True, "signs": [{"key": "hwa_wool", "confidence": 0.8,
                                                                       "where": "needle bases"}],
                                           "look_alikes": "", "summary": "White wool at several needle bases."})))
    o = c.post(f"{V}/observations/{oid}/inspect", headers=h).json()
    assert o["ai_inspection"]["summary"].startswith("White wool")
    hwa = next(f for f in o["findings"] if f["condition"] == "hwa")
    assert hwa["level"] == "possible" and "AI photo check" in hwa["evidence"][0]  # AI alone is never "likely"
    req = fake.requests[-1]
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert sum(1 for b in req["messages"][0]["content"] if b["type"] == "image") == 1  # only the twig photo
