"""Sections, disease hotspots, trends, landmarks and the hemlock check."""

from fastapi.testclient import TestClient

from hemlock_sentinel.acquisition.quality import assess
from hemlock_sentinel.api.demo_seed import CHATTAHOOCHEE, DEMO_EMAIL, DEMO_PASSWORD, LEGACY, seed_demo
from hemlock_sentinel.api.server import create_api
from tests.helpers import tree_view
from tests.integration.test_accounts_forests import _jpeg, make_accounts, signup

V = "/api/v1"


def demo(tmp_path):
    acc = make_accounts(tmp_path)
    seed_demo(acc, now=1_790_000_000.0)
    c = TestClient(create_api(accounts=acc))
    tok = c.post(f"{V}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    f = next(f for f in c.get(f"{V}/forests", headers=h).json() if f["name"] == CHATTAHOOCHEE)
    return c, acc, {**h, "X-Forest-Id": str(f["forest_id"])}


def test_chattahoochee_landmarks_sections_and_hotspots(tmp_path):
    c, _, h = demo(tmp_path)
    lm = c.get(f"{V}/landmarks", headers=h).json()
    kinds = {x["properties"]["kind"] for x in lm["features"]}
    assert {"stream", "peak", "ridge", "trail"} <= kinds and lm["approximate"] is True
    secs = c.get(f"{V}/sections", headers=h).json()
    assert {s["name"] for s in secs} >= {"Lower Cooper Creek", "Mulky Creek", "Shanty Branch"}
    assert sum(s["trees"] for s in secs) >= 50

    a = c.get(f"{V}/analysis", headers=h).json()
    assert set(a["hotspots"]) == {"hwa", "ehs", "drought_stress"} and len(a["sections"]) == len(secs)
    assert len(a["trends"]) >= 3 and all("conditions" in t for t in a["trends"])
    # the seed puts scale on Mulky Creek and drought on Shanty Branch: their sections lead those conditions
    by = {s["name"]: s for s in secs}
    share = lambda s, k: s["condition_counts"][k] / max(s["trees"], 1)  # noqa: E731
    assert share(by["Mulky Creek"], "ehs") > share(by["Lower Cooper Creek"], "ehs")
    assert share(by["Shanty Branch"], "drought_stress") > share(by["Lower Cooper Creek"], "drought_stress")
    # HWA is worse downstream (west) and gets worse over time
    assert by["Lower Cooper Creek"]["mean_severity"] > by["Mulky Creek"]["mean_severity"]
    sev = [t["mean_severity"] for t in a["trends"] if t["mean_severity"] is not None]
    assert sev[-1] > sev[0]

    sa = c.get(f"{V}/sections/{by['Mulky Creek']['section_id']}/analysis", headers=h).json()
    assert sa["section"]["name"] == "Mulky Creek" and sa["summary"]["trees"] == by["Mulky Creek"]["trees"]
    trees = c.get(f"{V}/trees?limit=5", headers=h).json()["items"]
    assert all(set(t["conditions"]) <= {"hwa", "ehs", "drought_stress"} for t in trees)
    assert any(t["conditions"] for t in trees)


def test_user_sections_crud(tmp_path):
    c, _, h = demo(tmp_path)
    w, s_, e, n = -84.08, 34.755, -84.06, 34.77
    r = c.post(f"{V}/sections", json={"name": "My plot", "west": w, "south": s_, "east": e, "north": n}, headers=h)
    assert r.status_code == 201 and r.json()["trees"] > 0
    assert c.post(f"{V}/sections", json={"name": "my plot", "west": w, "south": s_, "east": e, "north": n},
                  headers=h).json()["error"]["code"] == "section_exists"
    assert c.post(f"{V}/sections", json={"name": "Bad", "west": e, "south": s_, "east": w, "north": n},
                  headers=h).json()["error"]["code"] == "bad_area"
    sid = r.json()["section_id"]
    assert c.delete(f"{V}/sections/{sid}", headers=h).status_code == 204
    assert c.get(f"{V}/sections/{sid}/analysis", headers=h).status_code == 404


def test_seed_upgrades_old_demo_account(tmp_path):
    acc = make_accounts(tmp_path)
    u = acc.register(DEMO_EMAIL, DEMO_PASSWORD, "Demo Field Team")
    old = acc.create_forest(u.user_id, LEGACY[0])
    seed_demo(acc)
    names = {f.name for f in acc.forests(u.user_id)}
    assert LEGACY[0] not in names and CHATTAHOOCHEE in names
    assert not (acc.root / "forests" / str(old.forest_id)).exists()


def test_species_check_and_per_view_hemlock_score(tmp_path):
    c = TestClient(create_api(accounts=make_accounts(tmp_path)))
    h = signup(c, "s@example.org")
    f = c.post(f"{V}/forests", json={"name": "S"}, headers=h).json()
    hf = {**h, "X-Forest-Id": str(f["forest_id"])}
    r = c.post(f"{V}/species-check", files={"image": ("a.jpg", _jpeg(tree_view(3, 0)), "image/jpeg")}, headers=hf)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["verdict"] in ("hemlock", "not_hemlock", "unsure") and 0 <= j["hemlock_probability"] <= 1
    assert j["top"][0]["probability"] >= j["top"][-1]["probability"] and j["quality"]["accepted"]
    assert c.get(f"{V}/trees", headers=hf).json()["total"] == 0  # nothing stored
    cap = c.post(f"{V}/captures", headers=hf).json()["capture_id"]
    v = c.post(f"{V}/captures/{cap}/views", files={"image": ("a.jpg", _jpeg(tree_view(3, 0)), "image/jpeg")},
               headers=hf).json()
    assert v["view"]["hemlock_probability"] is not None and v["view"]["top_species"]["label"]
    assert "texture_coverage" in v["view"]["metrics"]


def test_distance_warning():
    import cv2
    import numpy as np

    bark = tree_view(4, 0)
    assert not assess(bark).warnings and assess(bark).metrics["texture_coverage"] > 0.85
    h, w = bark.shape[:2]
    far = cv2.GaussianBlur(bark, (0, 0), 25)
    small = cv2.resize(bark, (w // 3, h // 3))
    far[h // 3: h // 3 + small.shape[0], w // 3: w // 3 + small.shape[1]] = small
    q = assess(np.ascontiguousarray(far))
    # a mostly smooth frame is rejected outright; a less extreme one only gets the distance hint
    assert q.metrics["texture_coverage"] < 0.6 and (q.problems or any(x.startswith("too far") for x in q.warnings))
    small = cv2.resize(bark, (int(w * 0.7), int(h * 0.7)))
    far = cv2.GaussianBlur(bark, (0, 0), 25)
    far[(h - small.shape[0]) // 2: (h - small.shape[0]) // 2 + small.shape[0],
        (w - small.shape[1]) // 2: (w - small.shape[1]) // 2 + small.shape[1]] = small
    q = assess(np.ascontiguousarray(far))
    assert not q.problems and q.warnings and q.metrics["texture_coverage"] < 0.85


def test_delete_forest_needs_exact_name(tmp_path):
    from tests.integration.test_accounts_forests import capture

    acc = make_accounts(tmp_path)
    c = TestClient(create_api(accounts=acc))
    h = signup(c, "d@example.org")
    other = signup(c, "o@example.org")
    f = c.post(f"{V}/forests", json={"name": "Ridge Plot"}, headers=h).json()
    capture(c, h, f["forest_id"], seed=1)
    fid = f["forest_id"]
    assert c.delete(f"{V}/forests/{fid}?confirm_name=ridge plot", headers=h).json()["error"]["code"] == "name_mismatch"
    assert c.delete(f"{V}/forests/{fid}?confirm_name=Ridge Plot", headers=other).status_code == 404
    assert c.delete(f"{V}/forests/{fid}?confirm_name=Ridge Plot", headers=h).status_code == 204
    assert c.get(f"{V}/forests", headers=h).json() == []
    assert not (acc.root / "forests" / str(fid)).exists()


def test_delete_tree_removes_visits_and_photos(tmp_path):
    from tests.integration.test_accounts_forests import capture

    acc = make_accounts(tmp_path)
    c = TestClient(create_api(accounts=acc))
    h = signup(c, "t@example.org")
    f = c.post(f"{V}/forests", json={"name": "T"}, headers=h).json()
    hf = {**h, "X-Forest-Id": str(f["forest_id"])}
    a = capture(c, h, f["forest_id"], seed=1, severity=2, signs="hwa_wool")
    capture(c, h, f["forest_id"], seed=2)
    repo = acc.pipeline(acc.forest(1, f["forest_id"])).repo
    keys = [r[0] for r in repo.query("SELECT image_key FROM views v JOIN observations o USING(observation_id) "
                                     "WHERE o.tree_id=?", (a["tree_id"],))]
    assert c.delete(f"{V}/trees/{a['tree_id']}", headers=hf).status_code == 204
    assert c.get(f"{V}/trees/{a['tree_id']}", headers=hf).status_code == 404
    assert [t["tree_id"] for t in c.get(f"{V}/trees", headers=hf).json()["items"]] == ["H-002"]
    assert not repo.query("SELECT 1 FROM tree_health WHERE observation_id=?", (a["observation_id"],))
    storage = acc.pipeline(acc.forest(1, f["forest_id"])).storage
    assert keys and not any(__import__("os").path.exists(storage.path(k)) for k in keys)
    # IDs are never reused
    assert capture(c, h, f["forest_id"], seed=3)["tree_id"] == "H-003"
