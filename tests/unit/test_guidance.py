"""AI-guided active scanning: the policy turns the live ranking into one reasoned request."""

from hemlock_sentinel.pipeline.guidance import Preview, guide


def pv(n, cands=(), agreement=1.0, leaders=None, species_ok=None, hem=None, gallery=10):
    c = [{"tree_id": t, "probability": p, "global_score": g} for t, p, g in cands]
    return Preview(n, c, agreement, leaders or ([c[0]["tree_id"]] * n if c else []), species_ok, hem, gallery,
                   match_threshold=0.5, view_match_threshold=0.8)


def test_first_photo_and_rejected_photo():
    assert guide(pv(0), set()).state == "start"
    g = guide(pv(1, [("H-1", 0.9, 0.9)]), {"trunk_north"}, "blurry: hold the phone steady")
    assert g.state == "retake" and "blurry" in g.detail


def test_clear_match_waits_for_the_minimum_then_is_ready():
    g = guide(pv(1, [("H-1", 0.9, 0.9), ("H-2", 0.01, 0.4)]), {"trunk_north"})
    assert g.state == "confident" and not g.ready and g.next_view.key == "trunk_right"
    g = guide(pv(3, [("H-1", 0.95, 0.9), ("H-2", 0.01, 0.4)]), {"trunk_north", "trunk_right", "trunk_right2"})
    assert g.state == "confident" and g.ready and g.next_view is None and "H-1" in g.title


def test_two_close_trees_ask_for_a_close_up_beyond_the_minimum():
    done = {"trunk_north", "trunk_right", "trunk_right2"}
    g = guide(pv(3, [("H-1", 0.4, 0.8), ("H-2", 0.35, 0.79)]), done)
    assert g.state == "ambiguous" and g.needs_more and g.next_view.key == "trunk_low_close"
    assert "H-1" in g.detail and "H-2" in g.detail
    g = guide(pv(4, [("H-1", 0.4, 0.8), ("H-2", 0.35, 0.79)]), done | {"trunk_low_close"})
    assert g.next_view.key == "trunk_right3"  # the request changes with what was already taken


def test_photos_that_disagree_and_species_doubt():
    g = guide(pv(2, [("H-1", 0.4, 0.8)], agreement=0.5, leaders=["H-1", "H-7"]), {"trunk_north", "trunk_right"})
    assert g.state == "contradicting" and "H-7" in g.detail and g.needs_more
    g = guide(pv(2, [("H-1", 0.4, 0.8)], species_ok=False, hem=0.21), {"trunk_north", "trunk_right"})
    assert g.state == "species_doubt" and "21%" in g.detail


def test_new_tree_and_empty_forest():
    g = guide(pv(3, [("H-1", 0.01, 0.3)]), {"trunk_north", "trunk_right", "trunk_right2"})
    assert g.state == "likely_new" and g.ready
    g = guide(pv(1, gallery=0), {"trunk_north"})
    assert g.state == "first_tree" and not g.ready


def test_stops_asking_after_six_trunk_photos():
    keys = {"trunk_north", "trunk_right", "trunk_right2", "trunk_right3", "trunk_north_high", "trunk_low_close"}
    g = guide(pv(6, [("H-1", 0.3, 0.8), ("H-2", 0.28, 0.79)]), keys)
    assert g.next_view is None and g.ready and not g.needs_more


def test_titles_and_details_stay_short():
    cases = [pv(0), pv(1, [("H-1", 0.9, 0.9)]), pv(3, [("H-1", 0.4, 0.8), ("H-2", 0.35, 0.79)]),
             pv(2, [("H-1", 0.4, 0.8)], agreement=0.5, leaders=["H-1", "H-7"]), pv(3, [("H-1", 0.01, 0.3)])]
    for c in cases:
        g = guide(c, {"trunk_north", "trunk_right", "trunk_right2"} if c.n_views >= 3 else {"trunk_north"})
        assert len(g.title) <= 28 and len(g.detail) <= 70, (g.title, g.detail)
