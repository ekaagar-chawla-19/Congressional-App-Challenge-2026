"""Sign-in, per-forest databases, severity ratings, forest map, demo account (mock model)."""

import cv2
import pytest
from fastapi.testclient import TestClient

from hemlock_sentinel.api.accounts import Accounts
from hemlock_sentinel.api.demo_seed import DEMO_EMAIL, DEMO_PASSWORD, FORESTS, seed_demo
from hemlock_sentinel.api.server import create_api
from hemlock_sentinel.pipeline.runtime import MockRuntime
from hemlock_sentinel.reid.calibration import Calibration
from tests.helpers import species_fn_factory, tree_view

V = "/api/v1"


def _jpeg(img):
    return cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


def make_accounts(tmp_path):
    rt = MockRuntime(input_size=64, embedding_dim=128, species_fn=species_fn_factory())
    cal = Calibration(species_threshold=0.6, global_threshold=0.8, match_threshold=0.5,
                      view_contradiction_margin=0.05, view_match_threshold=0.4)
    return Accounts(tmp_path / "data", rt, cal)


@pytest.fixture
def client(tmp_path):
    acc = make_accounts(tmp_path)
    return TestClient(create_api(accounts=acc)), acc


def signup(c, email, name="Team"):
    r = c.post(f"{V}/auth/register", json={"email": email, "password": "correct horse", "name": name})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def capture(c, h, forest, seed, jitter=0, **form):
    files = [("images", (f"{v}.jpg", _jpeg(tree_view(seed, v, jitter)), "image/jpeg")) for v in range(3)]
    r = c.post(f"{V}/identify", files=files, data=form, headers={**h, "X-Forest-Id": str(forest)})
    assert r.status_code == 200, r.text
    return r.json()


def test_sign_in_flow(client):
    c, _ = client
    assert c.get(f"{V}/me").json()["error"]["code"] == "not_signed_in"
    signup(c, "ranger@example.org")
    assert c.post(f"{V}/auth/register", json={"email": "RANGER@example.org", "password": "another one",
                                              "name": "x"}).json()["error"]["code"] == "email_taken"
    bad = c.post(f"{V}/auth/login", json={"email": "ranger@example.org", "password": "wrong password"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "bad_credentials"
    tok = c.post(f"{V}/auth/login", json={"email": "ranger@example.org", "password": "correct horse"}).json()
    h = {"Authorization": f"Bearer {tok['token']}"}
    me = c.get(f"{V}/me", headers=h).json()
    assert me["user"]["email"] == "ranger@example.org" and me["forests"] == []
    assert c.post(f"{V}/auth/logout", headers=h).status_code == 204
    assert c.get(f"{V}/me", headers=h).status_code == 401
    assert c.post(f"{V}/auth/register", json={"email": "x@y.z", "password": "short", "name": "x"}).status_code == 422


def test_forests_are_separate_databases_and_private(client):
    c, _ = client
    alice, bob = signup(c, "alice@example.org"), signup(c, "bob@example.org")
    f1 = c.post(f"{V}/forests", json={"name": "Cloudland", "lat": 34.83, "lon": -85.48}, headers=alice).json()
    f2 = c.post(f"{V}/forests", json={"name": "Cooper Creek"}, headers=alice).json()
    assert c.post(f"{V}/forests", json={"name": "Cloudland"}, headers=alice).status_code == 409
    fb = c.post(f"{V}/forests", json={"name": "Cloudland"}, headers=bob).json()  # same name, other user: fine

    r1 = capture(c, alice, f1["forest_id"], seed=1, lat="34.831", lon="-85.481", severity="2",
                 health_notes="white wool on lower branches")
    assert (r1["status"], r1["tree_id"]) == ("new", "H-001")
    # same tree photographed again, other forest: separate database, so it is NEW there (own numbering)
    assert capture(c, alice, f2["forest_id"], seed=1, jitter=3)["tree_id"] == "H-001"
    assert c.get(f"{V}/trees", headers={**alice, "X-Forest-Id": str(f2["forest_id"])}).json()["total"] == 1
    # revisit in the first forest matches
    r2 = capture(c, alice, f1["forest_id"], seed=1, jitter=4, lat="34.8311", lon="-85.4811", severity="3")
    assert (r2["status"], r2["tree_id"]) == ("existing", "H-001")

    # bob cannot see or write alice's forest, even by guessing its id
    for path in (f"/forests/{f1['forest_id']}", f"/forests/{f1['forest_id']}/map"):
        assert c.get(V + path, headers=bob).json()["error"]["code"] == "forest_not_found"
    assert c.get(f"{V}/trees", headers={**bob, "X-Forest-Id": str(f1["forest_id"])}).status_code == 404
    assert c.get(f"{V}/trees", headers={**bob, "X-Forest-Id": str(fb["forest_id"])}).json()["total"] == 0
    assert c.get(f"{V}/trees", headers=alice).json()["error"]["code"] == "forest_required"

    # captures are bound to their forest
    cid = c.post(f"{V}/captures", headers={**alice, "X-Forest-Id": str(f1["forest_id"])}).json()["capture_id"]
    assert c.get(f"{V}/captures/{cid}", headers={**alice, "X-Forest-Id": str(f2["forest_id"])}).status_code == 404
    assert c.get(f"{V}/captures/{cid}", headers={**bob, "X-Forest-Id": str(fb["forest_id"])}).status_code == 404

    # severity: latest rating per tree, full history per visit
    h1 = {**alice, "X-Forest-Id": str(f1["forest_id"])}
    tree = c.get(f"{V}/trees/H-001", headers=h1).json()
    assert tree["severity"] == 3 and tree["location"]["lat"] == pytest.approx(34.8311)
    assert [o["severity"] for o in tree["observations"]] == [2, 3]
    assert tree["observations"][0]["health_notes"] == "white wool on lower branches"
    oid = tree["observations"][1]["observation_id"]
    assert c.put(f"{V}/observations/{oid}/health", json={"severity": 1, "notes": "re-rated"},
                 headers=h1).json()["severity"] == 1
    assert c.put(f"{V}/observations/{oid}/health", json={"severity": 7}, headers=h1).status_code == 422

    # map = GeoJSON with severity
    m = c.get(f"{V}/forests/{f1['forest_id']}/map", headers=alice).json()
    assert m["type"] == "FeatureCollection" and len(m["features"]) == 1
    p = m["features"][0]
    assert p["geometry"]["coordinates"] == [pytest.approx(-85.4811), pytest.approx(34.8311)]
    assert p["properties"]["severity"] == 1 and p["properties"]["severity_label"] == "light"
    assert [h["severity"] for h in p["properties"]["severity_history"]] == [2, 1]
    assert c.get(f"{V}/map", headers=h1).json()["features"] == m["features"]
    m2 = c.get(f"{V}/forests/{f2['forest_id']}/map", headers=alice).json()
    assert m2["features"] == [] and m2["trees_without_location"] == ["H-001"]

    # account overview has everything
    me = c.get(f"{V}/me", headers=alice).json()
    assert me["totals"]["forests"] == 2 and me["totals"]["trees"] == 2 and me["totals"]["observations"] == 3
    byname = {f["name"]: f for f in me["forests"]}
    assert byname["Cloudland"]["severity_counts"]["light"] == 1
    assert byname["Cooper Creek"]["severity_counts"]["unrated"] == 1
    assert byname["Cloudland"]["center"] == {"lat": 34.83, "lon": -85.48, "accuracy_m": None}


def test_demo_account(client):
    c, acc = client
    u = seed_demo(acc, now=1_790_000_000.0)
    assert seed_demo(acc).user_id == u.user_id  # idempotent
    tok = c.post(f"{V}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    me = c.get(f"{V}/me", headers=h).json()
    assert sorted(f["tree_count"] for f in me["forests"]) == sorted(n for *_, n, _ in FORESTS)
    assert me["totals"]["severe"] > 0 and me["totals"]["none"] > 0
    f = me["forests"][0]
    m = c.get(f"{V}/forests/{f['forest_id']}/map", headers=h).json()
    assert len(m["features"]) == f["tree_count"]
    lon, lat = m["features"][0]["geometry"]["coordinates"]
    assert abs(lat - f["center"]["lat"]) < 0.01 and abs(lon - f["center"]["lon"]) < 0.01
    # a real capture in a demo forest: the placeholder trees never match it
    r = capture(c, h, f["forest_id"], seed=5)
    assert r["status"] == "new" and r["tree_id"] == f"H-{f['tree_count'] + 1:03d}"
    assert c.get("/map").status_code == 200 and "leaflet" in c.get("/map").text
