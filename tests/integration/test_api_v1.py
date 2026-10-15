"""Mobile API v1, end to end with the mock model."""

import cv2
import pytest
from fastapi.testclient import TestClient

from hemlock_sentinel.api.server import create_api
from tests.helpers import build, species_fn_factory, tree_view

V = "/api/v1"


def _jpeg(img):
    return cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


def _files(imgs):
    return [("images", (f"v{i}.jpg", _jpeg(im), "image/jpeg")) for i, im in enumerate(imgs)]


@pytest.fixture
def api(tmp_path):
    pipe = build(tmp_path)
    return TestClient(create_api(pipe)), pipe


def guided(c, imgs, **identify):
    cid = c.post(f"{V}/captures").json()["capture_id"]
    for im in imgs:
        r = c.post(f"{V}/captures/{cid}/views", files={"image": ("v.jpg", _jpeg(im), "image/jpeg")})
        assert r.status_code == 200, r.text
    return cid, c.post(f"{V}/captures/{cid}/identify", json=identify or None).json()


def oneshot(c, imgs, **form):
    return c.post(f"{V}/identify", files=_files(imgs), data=form).json()


def test_meta(api):
    c, _ = api
    assert c.get(f"{V}/health").json()["status"] == "ok"
    p = c.get(f"{V}/protocol").json()
    assert p["min_views"] == 3 and [v["key"] for v in p["views"]][:3] == ["trunk_north", "trunk_right", "trunk_right2"]
    m = c.get(f"{V}/model").json()
    assert m["reid_supported_species"] == ["tsuga_canadensis"] and m["embedding_dim"] == 128
    spec = c.get("/openapi.json").json()
    assert f"{V}/captures/{{capture_id}}/identify" in spec["paths"]


def test_guided_new_then_existing_with_location(api):
    c, _ = api
    cid = c.post(f"{V}/captures").json()["capture_id"]
    for v in range(3):
        r = c.post(f"{V}/captures/{cid}/views", files={"image": ("v.jpg", _jpeg(tree_view(1, v)), "image/jpeg")},
                   data={"heading_deg": str(10 + 90 * v)}).json()
        assert r["view"]["accepted"], r
    assert r["can_identify"] and r["next_view"]["key"] == "branching"
    r1 = c.post(f"{V}/captures/{cid}/identify",
                json={"location": {"lat": 34.75, "lon": -84.1, "accuracy_m": 4}}).json()
    assert (r1["status"], r1["tree_id"], r1["action"]) == ("new", "H-001", "done")
    assert r1["species"]["name"] == "Eastern hemlock" and r1["observation_id"]
    assert c.post(f"{V}/captures/{cid}/identify").json() == r1  # idempotent
    assert c.post(f"{V}/captures/{cid}/views", files={"image": ("v.jpg", _jpeg(tree_view(1, 0)))}).status_code == 409
    state = c.get(f"{V}/captures/{cid}").json()
    assert state["result"]["tree_id"] == "H-001" and state["accepted_views"] == 3

    _, r2 = guided(c, [tree_view(1, v, 4) for v in range(3)])
    assert (r2["status"], r2["tree_id"]) == ("existing", "H-001")
    assert r2["candidates"][0]["tree_id"] == "H-001" and 0 <= r2["probability"] <= 1

    tree = c.get(f"{V}/trees/H-001").json()
    assert tree["observation_count"] == 2 and tree["name"] == "Eastern hemlock"
    first = tree["observations"][0]
    assert first["location"] == {"lat": 34.75, "lon": -84.1, "accuracy_m": 4.0}
    assert first["timestamp"].endswith("Z") and [v["heading_deg"] for v in first["views"]] == [10, 100, 190]
    img = c.get(first["views"][0]["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert c.get(tree["thumbnail_url"]).status_code == 200


def test_bad_photo_reported_and_retaken(api):
    c, _ = api
    cid = c.post(f"{V}/captures").json()["capture_id"]
    blurry = cv2.GaussianBlur(tree_view(2, 0), (0, 0), 6)
    r = c.post(f"{V}/captures/{cid}/views", files={"image": ("v.jpg", _jpeg(blurry))}).json()
    assert not r["view"]["accepted"] and r["accepted_views"] == 0
    assert any("blurry" in p for p in r["view"]["problems"]) and r["next_view"]["key"] == "trunk_north"
    bad = c.post(f"{V}/captures/{cid}/views", files={"image": ("v.jpg", b"not an image")})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "bad_image"
    r = c.post(f"{V}/captures/{cid}/identify").json()
    assert r["status"] == "recapture" and r["action"] == "retake" and r["observation_id"] is None


def test_uncertain_flow_and_review_queue(api):
    c, pipe = api
    for seed in (50, 51):
        assert guided(c, [tree_view(seed, v) for v in range(3)])[1]["status"] == "new"
    cid, r = guided(c, [tree_view(50, 0, 3), tree_view(50, 1, 3), tree_view(51, 2, 3)])
    assert r["status"] == "uncertain" and r["action"] == "capture_another_view"
    assert r["next_view"]["key"] == "trunk_right3" and r["observation_id"] is None
    c.post(f"{V}/captures/{cid}/views", files={"image": ("v.jpg", _jpeg(tree_view(50, 3, 3)))})
    r = c.post(f"{V}/captures/{cid}/identify", json={"force_commit": True}).json()
    assert r["status"] == "uncertain" and r["action"] == "review" and r["tree_id"] is None
    queue = c.get(f"{V}/observations", params={"status": "uncertain", "unassigned": True}).json()
    assert queue["total"] == 1 and queue["items"][0]["observation_id"] == r["observation_id"]
    assert {x["tree_id"] for x in queue["items"][0]["candidates"]} == {"H-001", "H-002"}
    a = c.post(f"{V}/observations/{r['observation_id']}/assign", json={"tree_id": "H-001"}).json()
    assert a == {"observation_id": r["observation_id"], "tree_id": "H-001", "created_tree": False}
    assert pipe.repo.get_tree("H-001").observation_count == 2
    assert c.get(f"{V}/observations", params={"status": "uncertain", "unassigned": True}).json()["total"] == 0
    assert c.get(f"{V}/observations/{r['observation_id']}").json()["status"] == "user_confirmed"


def test_oneshot_correction_new_and_merge(api):
    c, pipe = api
    r1 = oneshot(c, [tree_view(70, v) for v in range(3)])
    assert (r1["status"], r1["tree_id"], r1["action"]) == ("new", "H-001", "done") and len(r1["views"]) == 3
    r2 = oneshot(c, [tree_view(71, v) for v in range(3)], view_keys="trunk_north,trunk_right,trunk_right2",
                 lat="34.7", lon="-84.0")
    assert r2["tree_id"] == "H-002"
    # one-tap correction: H-002 was really H-001 -> H-002 retired, number never reused
    a = c.post(f"{V}/observations/{r2['observation_id']}/assign", json={"tree_id": "H-001"}).json()
    assert a["tree_id"] == "H-001"
    assert [t["tree_id"] for t in c.get(f"{V}/trees").json()["items"]] == ["H-001"]
    assert c.get(f"{V}/trees/H-002").json()["error"]["code"] == "tree_merged"
    # ...and back out to a brand-new tree
    a = c.post(f"{V}/observations/{r2['observation_id']}/assign", json={"tree_id": "new"}).json()
    assert a["created_tree"] and a["tree_id"] == "H-003"
    # merge duplicate H-003 into H-001
    m = c.post(f"{V}/trees/H-001/merge", json={"duplicate_tree_id": "H-003"}).json()
    assert m["observation_count"] == 2 and len(m["observations"]) == 2
    assert c.post(f"{V}/trees/H-001/merge", json={"duplicate_tree_id": "H-001"}).status_code == 400
    # the retrieval index follows the corrections
    r3 = oneshot(c, [tree_view(71, v, 2) for v in range(3)])
    assert r3["status"] == "existing" and r3["tree_id"] == "H-001"


def test_oneshot_dry_run_and_validation(api):
    c, pipe = api
    r = oneshot(c, [tree_view(80, v) for v in range(3)], commit="false")
    assert r["status"] == "new" and r["tree_id"] is None and r["observation_id"] is None
    assert pipe.repo.list_trees() == []
    for form, code in [({"view_keys": "trunk_north,trunk_north,trunk_right"}, "duplicate_view_key"),
                       ({"view_keys": "trunk_north,trunk_right"}, "length_mismatch"),
                       ({"view_keys": "a,b,c"}, "unknown_view"),
                       ({"lat": "34.0"}, "bad_location")]:
        res = c.post(f"{V}/identify", files=_files([tree_view(80, v) for v in range(3)]), data=form)
        assert res.status_code == 400 and res.json()["error"]["code"] == code, (form, res.text)
    res = c.post(f"{V}/identify", files=_files([tree_view(80, 0)]))
    assert res.json()["error"]["code"] == "wrong_view_count"
    res = c.post(f"{V}/identify", files=_files([tree_view(80, v) for v in range(3)]), data={"lat": "123", "lon": "0"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_request"


def test_unsupported_species_gets_no_id(tmp_path):
    c = TestClient(create_api(build(tmp_path, species_fn=species_fn_factory(supported=False))))
    r = oneshot(c, [tree_view(90, v) for v in range(3)])
    assert r["status"] == "unsupported_species" and r["tree_id"] is None
    assert r["species"]["label"] == "pinus_strobus"
    res = c.post(f"{V}/observations/{r['observation_id']}/assign", json={"tree_id": "new"})
    assert res.status_code == 400 and res.json()["error"]["code"] == "not_assignable"


def test_trees_list_notes_paging(api):
    c, _ = api
    for seed in (100, 101, 102):
        oneshot(c, [tree_view(seed, v) for v in range(3)])
    page = c.get(f"{V}/trees", params={"limit": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["items"][0]["tree_id"] == "H-003"
    assert c.get(f"{V}/trees", params={"limit": 2, "offset": 2}).json()["items"][0]["tree_id"] == "H-001"
    t = c.patch(f"{V}/trees/H-002", json={"notes": "near trail marker 4; light HWA"}).json()
    assert t["notes"] == "near trail marker 4; light HWA"
    assert c.get(f"{V}/trees/H-002").json()["notes"] == t["notes"]
    assert c.get(f"{V}/trees", params={"species": "acer_rubrum"}).json()["total"] == 0


def test_errors_and_auth(tmp_path):
    c = TestClient(create_api(build(tmp_path), api_key="s3cret"))
    assert c.get(f"{V}/health").status_code == 200  # no key needed
    r = c.get(f"{V}/trees")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    h = {"X-API-Key": "s3cret"}
    assert c.get(f"{V}/trees", headers=h).status_code == 200
    assert c.post(f"{V}/captures/nope/identify", headers=h).json()["error"]["code"] == "capture_not_found"
    assert c.get(f"{V}/observations/nope", headers=h).status_code == 404
    assert c.get(f"{V}/images/..%2Fetc", headers=h).status_code in (400, 404)
    assert c.get(f"{V}/images/{'0' * 64}.jpg", headers=h).json()["error"]["code"] == "image_not_found"


@pytest.mark.parametrize("detector_available", [True, False])
def test_original_photo_bytes_are_stored(tmp_path, monkeypatch, detector_available):
    from hemlock_sentinel.acquisition import privacy

    if not detector_available:
        monkeypatch.setattr(privacy, "_detector", False)
    c = TestClient(create_api(build(tmp_path)))
    assert c.get(f"{V}/health").json()["face_blur"] is detector_available
    imgs = [_jpeg(tree_view(110, v)) for v in range(3)]
    r = c.post(f"{V}/identify", files=[("images", (f"{i}.jpg", b, "image/jpeg")) for i, b in enumerate(imgs)]).json()
    views = c.get(f"{V}/observations/{r['observation_id']}").json()["views"]
    assert [c.get(v["image_url"]).content for v in views] == imgs  # no re-encode
