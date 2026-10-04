import numpy as np
import pytest

from hemlock_sentinel.reid.calibration import Calibration, LogisticCalibrator, threshold_at_fmr, threshold_max_f1
from hemlock_sentinel.reid.fusion import candidate_features, decide, match_probability, view_consistency


def test_threshold_at_fmr_controls_empirical_fmr():
    rng = np.random.default_rng(0)
    imp = rng.normal(0.2, 0.1, 1000)
    for target in (0.0, 0.01, 0.05, 0.2):
        t = threshold_at_fmr(imp, target)
        assert (imp >= t).mean() <= target + 1e-12


def test_threshold_at_fmr_zero_is_above_max():
    imp = np.array([0.1, 0.5, 0.3])
    assert threshold_at_fmr(imp, 0.0) > 0.5


def test_threshold_max_f1_separable():
    t = threshold_max_f1(np.array([0.8, 0.9]), np.array([0.1, 0.2]))
    assert 0.2 < t <= 0.8


def test_logistic_calibrator_roundtrip(tmp_path):
    rng = np.random.default_rng(0)
    X = np.r_[rng.normal(0.8, 0.1, (50, 1)), rng.normal(0.3, 0.1, (50, 1))]
    y = np.r_[np.ones(50), np.zeros(50)]
    lc = LogisticCalibrator(["global"]).fit(X, y)
    p = lc.predict_proba(np.array([[0.9], [0.2]]))
    assert p[0] > 0.9 and p[1] < 0.1
    cal = Calibration(fusers={"global": lc}, match_threshold=0.7)
    cal.save(tmp_path / "c.json")
    cal2 = Calibration.load(tmp_path / "c.json")
    assert np.allclose(cal2.fusers["global"].predict_proba(np.array([[0.9]])), p[0])


def test_view_consistency_flags_contradiction():
    names = ["H-017", "H-044"]
    s = np.array([[0.94, 0.5], [0.91, 0.5], [0.6, 0.93], [0.92, 0.5]])
    c = view_consistency(s, names, "H-017", margin=0.1)
    assert c.contradicting_views == [2] and c.agreement == pytest.approx(0.75)
    c2 = view_consistency(s[[0, 1, 3]], names, "H-017")
    assert not c2.contradicted and c2.agreement == 1.0


def test_candidate_features_gap_and_agreement():
    names = ["A", "B", "C"]
    agg = np.array([0.9, 0.6, 0.3])
    views = np.array([[0.9, 0.5, 0.1], [0.4, 0.8, 0.1]])
    f = candidate_features(agg, views, names, "A", local=1.5)
    assert f["global"] == pytest.approx(0.9)
    assert f["gap"] == pytest.approx(0.3)
    assert f["agreement"] == pytest.approx(0.5)
    assert f["local"] == 1.5 and "structure" not in f


def test_match_probability_falls_back_to_available_fuser():
    lc = LogisticCalibrator(["global", "gap", "agreement"], coef=[5.0, 0, 0], intercept=0.0,
                            mean=[0.5, 0, 0], scale=[0.1, 1, 1])
    cal = Calibration(fusers={"global+gap+agreement": lc})
    p, key = match_probability({"global": 0.9, "gap": 0.1, "agreement": 1.0, "local": 3.0}, cal)
    assert key == "global+gap+agreement" and p > 0.99


def test_match_probability_global_threshold_when_no_fuser():
    cal = Calibration(global_threshold=0.7)
    assert match_probability({"global": 0.8, "gap": 0.1, "agreement": 1}, cal) == (1.0, "global_threshold")
    assert match_probability({"global": 0.6, "gap": 0.1, "agreement": 1}, cal)[0] == 0.0


def test_decide_new_existing_uncertain():
    cal = Calibration(global_threshold=0.7, match_threshold=0.5, view_contradiction_margin=0.1)
    assert decide([], cal).kind == "new"
    feats = [("H-001", {"global": 0.9, "gap": 0.2, "agreement": 1.0}),
             ("H-002", {"global": 0.6, "gap": -0.2, "agreement": 0.0})]
    d = decide(feats, cal)
    assert d.kind == "existing" and d.tree_id == "H-001"
    d = decide([("H-002", {"global": 0.6, "gap": 0.0, "agreement": 0})], cal)
    assert d.kind == "new" and d.tree_id is None
    vs = np.array([[0.9, 0.5], [0.9, 0.5], [0.5, 0.95]])
    d = decide(feats, cal, vs, ["H-001", "H-002"])
    assert d.kind == "uncertain" and d.consistency.contradicting_views == [2]


def test_highest_similarity_is_not_blindly_accepted():
    # top candidate exists but is below the validated threshold -> new tree
    cal = Calibration(global_threshold=0.95)
    d = decide([("H-001", {"global": 0.94, "gap": 0.3, "agreement": 1.0})], cal)
    assert d.kind == "new"


def test_mixed_capture_is_uncertain_not_new():
    cal = Calibration(global_threshold=0.9, view_match_threshold=0.8)
    feats = [("H-001", {"global": 0.6, "gap": 0.2, "agreement": 0.67})]
    vs = np.array([[0.85, 0.1], [0.4, 0.1], [0.1, 0.3]])
    d = decide(feats, cal, vs, ["H-001", "H-002"])
    assert d.kind == "uncertain" and d.tree_id is None and "view 1" in d.reason
    cal.view_match_threshold = None
    assert decide(feats, cal, vs, ["H-001", "H-002"]).kind == "new"
