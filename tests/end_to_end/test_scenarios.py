"""Scenario tests from the acceptance criteria (mock model; real pipeline/DB/storage)."""

import cv2

from tests.helpers import build, capture, species_fn_factory, tree_view


def _enroll(app, seeds):
    ids = []
    for s in seeds:
        r = app.identify(capture(app, [tree_view(s, v) for v in range(3)]))
        assert r.status == "new"
        ids.append(r.tree_id)
    return ids


def test_new_tree_gets_new_sequential_id(tmp_path):
    app = build(tmp_path)
    assert _enroll(app, [10, 11, 12]) == ["H-001", "H-002", "H-003"]


def test_same_tree_gets_existing_id(tmp_path):
    app = build(tmp_path)
    ids = _enroll(app, [10, 11, 12])
    for s, tid in zip([10, 11, 12], ids):
        r = app.identify(capture(app, [tree_view(s, v, jitter_seed=9) for v in range(3)]))
        assert (r.status, r.tree_id) == ("existing", tid)


def test_similar_looking_different_tree_is_not_matched(tmp_path):
    app = build(tmp_path)
    _enroll(app, [20, 21])
    # same species, same procedural bark generator, different individual
    r = app.identify(capture(app, [tree_view(22, v) for v in range(3)]))
    assert r.status == "new" and r.tree_id == "H-003"


def test_bad_images_request_recapture(tmp_path):
    app = build(tmp_path)
    blurry = [cv2.GaussianBlur(tree_view(30, v), (0, 0), 6) for v in range(3)]
    views = capture(app, blurry)
    assert all(not v.accepted for v in views)
    assert any("blurry" in p for p in views[0].quality.problems)
    r = app.identify(views)
    assert r.status == "recapture" and app.repo.list_trees() == []


def test_unsupported_species_is_rejected(tmp_path):
    app = build(tmp_path, species_fn=species_fn_factory(supported=False))
    r = app.identify(capture(app, [tree_view(40, v) for v in range(3)]))
    assert r.status == "unsupported_species" and r.tree_id is None
    assert app.repo.list_trees() == []


def test_low_species_confidence_is_unknown(tmp_path):
    app = build(tmp_path, species_fn=species_fn_factory(confident=False))
    r = app.identify(capture(app, [tree_view(41, v) for v in range(3)]))
    assert r.status == "rejected_species" and r.species.species == "unknown"
    assert "retake" in r.message


def test_contradicting_view_is_flagged_not_hidden(tmp_path):
    app = build(tmp_path)
    _enroll(app, [50, 51])
    # the third trunk view was accidentally taken of the neighbouring tree
    views = [tree_view(50, 0, 3), tree_view(50, 1, 3), tree_view(51, 2, 3)]
    r = app.identify(capture(app, views), commit=False)
    assert r.status == "uncertain"
    assert r.decision.consistency.contradicting_views == [2]
    assert r.decision.consistency.per_view_top[2] == "H-002"
    assert app.repo.list_trees() and len(app.repo.list_trees()) == 2  # no spurious new tree


def test_longitudinal_history_is_ordered(tmp_path):
    app = build(tmp_path)
    for t, jitter in [(1000.0, 0), (2000.0, 1), (3000.0, 2)]:
        app.identify(capture(app, [tree_view(60, v, jitter) for v in range(3)]), now=t)
    obs = app.repo.get_observations("H-001")
    assert [o.timestamp for o in obs] == [1000.0, 2000.0, 3000.0]
    assert [o.decision for o in obs] == ["new", "existing", "existing"]
