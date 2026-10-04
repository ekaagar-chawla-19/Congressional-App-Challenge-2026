"""HTTP API of the handheld app, end to end (mock model)."""

import cv2
from fastapi.testclient import TestClient

from hemlock_sentinel.app.server import create_app
from tests.helpers import build, tree_view


def _jpeg(img):
    return cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


def test_guided_capture_flow(tmp_path):
    app = build(tmp_path)
    c = TestClient(create_app(app))
    proto = c.get("/api/protocol").json()
    assert proto["min_views"] == 3 and len(proto["views"]) == 5
    assert c.get("/").status_code == 200

    def session(seed, jitter):
        sid = c.post("/api/session").json()["session_id"]
        for v in range(3):
            r = c.post(f"/api/session/{sid}/view", files={"image": ("v.jpg", _jpeg(tree_view(seed, v, jitter)))}).json()
            assert r["view"]["accepted"], r
        assert r["can_identify"] and r["progress"] == 0.6
        assert r["next"]["key"] == "branching"
        return c.post(f"/api/session/{sid}/identify").json()

    r1 = session(1, 0)
    assert r1["status"] == "new" and r1["tree_id"] == "H-001" and r1["action"] == "done"
    assert r1["species"]["name"] == "Eastern hemlock"
    r2 = session(1, 4)
    assert r2["status"] == "existing" and r2["tree_id"] == "H-001"
    trees = c.get("/api/trees").json()
    assert [t["tree_id"] for t in trees] == ["H-001"] and trees[0]["observation_count"] == 2
    detail = c.get("/api/trees/H-001").json()
    assert len(detail["observations"]) == 2
    key = detail["observations"][0]["images"][0]
    assert c.get(f"/api/image/{key}").status_code == 200


def test_bad_view_is_reported_and_not_counted(tmp_path):
    c = TestClient(create_app(build(tmp_path)))
    sid = c.post("/api/session").json()["session_id"]
    blurry = cv2.GaussianBlur(tree_view(2, 0), (0, 0), 6)
    r = c.post(f"/api/session/{sid}/view", files={"image": ("v.jpg", _jpeg(blurry))}).json()
    assert not r["view"]["accepted"] and r["accepted_views"] == 0
    assert any("blurry" in p for p in r["view"]["problems"])
    assert c.post(f"/api/session/{sid}/view", files={"image": ("v.jpg", b"not an image")}).status_code == 400


def test_uncertain_asks_for_another_view_then_resolves(tmp_path):
    app = build(tmp_path)
    c = TestClient(create_app(app))
    for seed in (50, 51):
        sid = c.post("/api/session").json()["session_id"]
        for v in range(3):
            c.post(f"/api/session/{sid}/view", files={"image": ("v.jpg", _jpeg(tree_view(seed, v)))})
        assert c.post(f"/api/session/{sid}/identify").json()["status"] == "new"
    sid = c.post("/api/session").json()["session_id"]
    for img in [tree_view(50, 0, 3), tree_view(50, 1, 3), tree_view(51, 2, 3)]:
        c.post(f"/api/session/{sid}/view", files={"image": ("v.jpg", _jpeg(img))})
    r = c.post(f"/api/session/{sid}/identify").json()
    assert r["status"] == "uncertain" and r["action"] == "capture_another_view"
    # uncertainty asks for an extra TRUNK view (identity evidence), not the branching view
    assert r["next"]["key"] == "trunk_right3" and r["next"]["identity_view"]
    v = c.post(f"/api/session/{sid}/view", files={"image": ("v.jpg", _jpeg(tree_view(50, 3, 3)))}).json()
    assert v["view"]["view_type"] == "trunk_right3" and v["view"]["accepted"]
    r = c.post(f"/api/session/{sid}/identify", data={"force_commit": "true"}).json()
    assert r["status"] == "uncertain" and r["action"] == "review"
    assert c.post(f"/api/session/{sid}/resolve", data={"tree_id": "H-001"}).json()["tree_id"] == "H-001"
    assert app.repo.get_tree("H-001").observation_count == 2


def test_unknown_session_404(tmp_path):
    c = TestClient(create_app(build(tmp_path)))
    assert c.post("/api/session/nope/identify").status_code == 404


def test_one_tap_correction_merges_duplicate(tmp_path):
    app = build(tmp_path)
    c = TestClient(create_app(app))

    def session(seed, jitter=0):
        sid = c.post("/api/session").json()["session_id"]
        for v in range(3):
            c.post(f"/api/session/{sid}/view", files={"image": ("v.jpg", _jpeg(tree_view(seed, v, jitter)))})
        return sid, c.post(f"/api/session/{sid}/identify").json()

    session(70)
    sid, r = session(71)  # a different tree registered as new: H-002
    assert r["tree_id"] == "H-002"
    assert c.post(f"/api/session/{sid}/correct", data={"tree_id": "H-001"}).json()["tree_id"] == "H-001"
    assert [t["tree_id"] for t in c.get("/api/trees").json()] == ["H-001"]
    assert app.repo.get_tree("H-001").observation_count == 2
