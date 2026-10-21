"""gap_floor: a virtual competing tree so a forest with one tree does not hand out free matches."""

import numpy as np

from hemlock_sentinel.reid.fusion import candidate_features


def test_gap_without_floor_is_the_score_itself_in_a_one_tree_forest():
    f = candidate_features(np.array([0.8]), np.array([[0.8], [0.7]]), ["H-001"], "H-001")
    assert f["gap"] == 0.8 and f["agreement"] == 1.0


def test_gap_floor_acts_as_the_best_other_tree():
    f = candidate_features(np.array([0.8]), np.array([[0.8]]), ["H-001"], "H-001", gap_floor=0.6)
    assert abs(f["gap"] - 0.2) < 1e-6
    # a real competitor above the floor wins; below the floor the floor wins
    f = candidate_features(np.array([0.8, 0.7]), np.array([[0.8, 0.7]]), ["A", "B"], "A", gap_floor=0.6)
    assert abs(f["gap"] - 0.1) < 1e-6
    f = candidate_features(np.array([0.8, 0.3]), np.array([[0.8, 0.3]]), ["A", "B"], "A", gap_floor=0.6)
    assert abs(f["gap"] - 0.2) < 1e-6


def test_calibration_round_trips_gap_floor(tmp_path):
    from hemlock_sentinel.reid.calibration import Calibration

    Calibration(gap_floor=0.61).save(tmp_path / "c.json")
    assert Calibration.load(tmp_path / "c.json").gap_floor == 0.61
    assert Calibration().gap_floor is None  # delta's calibration file has no floor: unchanged behaviour
