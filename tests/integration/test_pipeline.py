"""images -> species -> embedding -> retrieval -> decision -> persistence, with a mock model."""

import numpy as np

from tests.helpers import build, capture, species_fn_factory, tree_view


def test_pipeline_flow_and_persistence(tmp_path):
    app = build(tmp_path)
    r1 = app.identify(capture(app, [tree_view(1, v) for v in range(3)]))
    assert r1.status == "new" and r1.tree_id == "H-001"
    assert r1.species.species == "tsuga_canadensis" and r1.species.reid_allowed

    r2 = app.identify(capture(app, [tree_view(1, v, jitter_seed=5) for v in range(3)]))
    assert r2.status == "existing" and r2.tree_id == "H-001", r2.message
    assert r2.decision.probability >= app.cal.match_threshold
    # every view agreed
    assert r2.decision.consistency.agreement == 1.0

    obs = app.repo.get_observations("H-001")
    assert len(obs) == 2 and all(len(o.views) == 3 for o in obs)
    assert all(v.image_key for o in obs for v in o.views)
    assert app.repo.get_tree("H-001").observation_count == 2


def test_local_features_are_stored_and_used(tmp_path):
    app = build(tmp_path, use_local_matching=True)  # off by default (E-local)
    app.identify(capture(app, [tree_view(2, v) for v in range(3)]))
    r = app.identify(capture(app, [tree_view(2, v, jitter_seed=3) for v in range(3)]))
    cand = r.decision.candidates[0]
    assert "local" in cand and cand["local"] > 1.0


def test_duplicate_view_is_rejected(tmp_path):
    app = build(tmp_path)
    img = tree_view(3, 0)
    views = capture(app, [img, img])
    assert views[1].duplicate_of == 0 and not views[1].accepted


def test_not_enough_views_requests_recapture(tmp_path):
    app = build(tmp_path)
    r = app.identify(capture(app, [tree_view(4, 0), tree_view(4, 1)]))
    assert r.status == "recapture"
    assert app.repo.list_trees() == []


def test_identify_without_commit_does_not_persist(tmp_path):
    app = build(tmp_path)
    r = app.identify(capture(app, [tree_view(5, v) for v in range(3)]), commit=False)
    assert r.status == "new" and r.tree_id is None and app.repo.list_trees() == []


def test_index_survives_restart(tmp_path):
    app = build(tmp_path)
    app.identify(capture(app, [tree_view(6, v) for v in range(3)]))
    app.repo.close()
    app2 = build(tmp_path)
    r = app2.identify(capture(app2, [tree_view(6, v, jitter_seed=1) for v in range(3)]))
    assert r.status == "existing" and r.tree_id == "H-001"


def test_local_matching_off_by_default(tmp_path):
    app = build(tmp_path)
    assert app.matcher is None
    app.identify(capture(app, [tree_view(2, v) for v in range(3)]))
    r = app.identify(capture(app, [tree_view(2, v, jitter_seed=3) for v in range(3)]))
    assert "local" not in r.decision.candidates[0]
