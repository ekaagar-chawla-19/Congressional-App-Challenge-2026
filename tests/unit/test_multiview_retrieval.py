import numpy as np
import pytest

from hemlock_sentinel.reid.multiview import aggregate_mean, l2_normalize
from hemlock_sentinel.reid.retrieval import EmbeddingIndex, cosine_similarity


def test_aggregate_mean_is_unit_norm_and_order_invariant():
    rng = np.random.default_rng(0)
    v = rng.normal(size=(4, 32))
    a = aggregate_mean(v)
    b = aggregate_mean(v[::-1])
    assert np.linalg.norm(a) == pytest.approx(1.0, abs=1e-5)
    assert np.allclose(a, b, atol=1e-6)


def test_aggregate_ignores_scale_of_individual_views():
    v = np.array([[1.0, 0.0], [0.0, 1.0]])
    a = aggregate_mean(v * np.array([[100.0], [1.0]]))
    assert np.allclose(a, [2 ** -0.5, 2 ** -0.5], atol=1e-6)


def test_aggregate_weights():
    v = np.array([[1.0, 0.0], [0.0, 1.0]])
    a = aggregate_mean(v, weights=np.array([1.0, 0.0]))
    assert np.allclose(a, [1.0, 0.0])
    with pytest.raises(ValueError):
        aggregate_mean(v, weights=np.array([1.0, -1.0]))
    with pytest.raises(ValueError):
        aggregate_mean(np.zeros((0, 3)))


def test_index_tree_score_is_max_over_observations():
    idx = EmbeddingIndex(3)
    idx.add("H-001", np.array([1.0, 0, 0]))
    idx.add("H-001", np.array([0, 1.0, 0]))
    idx.add("H-002", np.array([0, 0, 1.0]))
    s = idx.tree_scores(np.array([0.0, 1.0, 0.0]))
    assert s.shape == (1, 2)
    assert s[0, 0] == pytest.approx(1.0, abs=1e-3)
    assert s[0, 1] == pytest.approx(0.0, abs=1e-3)
    top = idx.search(np.array([0.0, 0.1, 1.0]), k=2)
    assert top[0].tree_id == "H-002" and top[0].rank == 1


def test_index_blocked_search_matches_unblocked():
    rng = np.random.default_rng(1)
    e = rng.normal(size=(50, 16))
    ids = [f"T-{i % 7}" for i in range(50)]
    a = EmbeddingIndex(16, block=4)
    b = EmbeddingIndex(16, block=4096)
    a.add_many(ids, e)
    b.add_many(ids, e)
    q = rng.normal(size=(3, 16))
    assert np.allclose(a.tree_scores(q), b.tree_scores(q), atol=1e-6)


def test_index_dim_mismatch():
    idx = EmbeddingIndex(4)
    with pytest.raises(ValueError):
        idx.add("x", np.ones(5))


def test_empty_index_search():
    assert EmbeddingIndex(4).search(np.ones(4)) == []


def test_cosine_basic():
    s = cosine_similarity(np.array([[1.0, 0]]), np.array([[1.0, 0], [0, 1.0], [-1.0, 0]]))
    assert np.allclose(s, [[1, 0, -1]])
