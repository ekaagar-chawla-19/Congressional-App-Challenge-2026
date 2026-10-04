import numpy as np
import pytest

from hemlock_sentinel.evaluation.benchmarks import closed_set_topk, genuine_impostor, run_open_set
from hemlock_sentinel.evaluation.metrics import bootstrap_ci, open_set_metrics, retrieval_metrics, roc_auc
from hemlock_sentinel.evaluation.splits import Observation


def test_retrieval_metrics_perfect_and_random():
    e = np.repeat(np.eye(4), 3, axis=0)
    lab = np.repeat(np.arange(4), 3)
    m = retrieval_metrics(e, lab)
    assert m["top1"] == 1.0 and m["mAP"] == 1.0 and m["n_queries"] == 12


def test_retrieval_skips_singletons():
    m = retrieval_metrics(np.eye(3), np.array([0, 1, 2]))
    assert m["n_queries"] == 0


def test_roc_auc():
    assert roc_auc(np.array([0.9, 0.8]), np.array([0.1, 0.2])) == 1.0
    assert roc_auc(np.array([0.1]), np.array([0.9])) == 0.0
    assert roc_auc(np.array([0.5]), np.array([0.5])) == 0.5


def test_open_set_metrics_definitions():
    truth = ["A", "B", None, None]
    pred = ["A", None, "A", None]
    m = open_set_metrics(pred, truth)
    assert m["known_accuracy"] == 0.5
    assert m["false_new_rate"] == 0.5
    assert m["false_match_rate"] == 0.25  # the new tree matched to A
    assert m["false_match_rate_new_trees"] == 0.5
    assert m["precision_existing"] == 0.5


def test_bootstrap_ci_contains_mean():
    v = np.random.default_rng(0).normal(0.5, 0.1, 200)
    lo, hi = bootstrap_ci(v)
    assert lo < v.mean() < hi


def test_open_set_protocol_on_separable_embeddings():
    obs, emb = [], {}
    for t in range(6):
        c = np.eye(6)[t]
        for k in range(3):
            paths = [f"t{t}_{k}_{v}" for v in range(3)]
            for p in paths:
                emb[p] = c + 0.01 * np.random.default_rng(hash(p) % 2**32).normal(size=6)
            obs.append(Observation(f"T{t}@c#{k}", f"T{t}", paths, "s"))
    qs = run_open_set(obs, emb, repeats=3)
    assert closed_set_topk(qs)["top1"] == 1.0
    g, i = genuine_impostor(qs)
    assert g.min() > i.max()
