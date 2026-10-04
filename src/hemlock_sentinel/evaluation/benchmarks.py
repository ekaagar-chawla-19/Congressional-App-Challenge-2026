"""Re-identification evaluation protocols on per-image embeddings.

Protocol (used for every number in docs/experiments.md):

* Trees in the evaluated split never appear in training (identity-disjoint).
* Each tree's images are grouped into disjoint simulated captures of V views
  (splits.make_observations). In BarkNet all images of a tree come from one
  session, so this is the "same tree / new view, same session" regime.
* Open set: in each of R random enrolments, half of the split's trees are
  enrolled with one observation; their other observations are "known"
  queries, all observations of the other half are "new tree" queries.
* Thresholds are fitted on the validation split and applied unchanged to test.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..reid.multiview import aggregate_mean, l2_normalize
from .splits import Observation, gallery_query_split, make_observations


@dataclass
class QueryScores:
    truth: str | None  # true tree id if enrolled, else None
    tree_ids: list[str]  # gallery trees, column order of `scores`
    scores: np.ndarray  # (T,) aggregated-query score per gallery tree
    view_scores: np.ndarray  # (V, T) per-view score per gallery tree
    obs: Observation
    rank: int | None  # rank of the true tree (1 = top), None for new trees


Aggregator = Callable[[np.ndarray], np.ndarray]  # (V, D) -> (D,)


def obs_matrix(obs: list[Observation], emb_of: dict[str, np.ndarray]) -> list[np.ndarray]:
    return [np.stack([emb_of[p] for p in o.paths]) for o in obs]


def run_open_set(obs: list[Observation], emb_of: dict[str, np.ndarray], aggregate: Aggregator = aggregate_mean,
                 enrolled_fraction: float = 0.5, repeats: int = 20, seed: int = 0,
                 score_mode: str = "aggregate") -> list[QueryScores]:
    """Return per-query scores over ``repeats`` random enrolments.

    score_mode: "aggregate" (cosine of aggregated query vs aggregated gallery
    observation) or "max_pair" (late fusion: max cosine over all query-view x
    gallery-view pairs) for the aggregation ablation.
    """
    out: list[QueryScores] = []
    for r in range(repeats):
        gal, known, new = gallery_query_split(obs, enrolled_fraction, seed + r)
        tids = [g.tree_id for g in gal]
        gal_views = [l2_normalize(np.stack([emb_of[p] for p in g.paths])) for g in gal]
        gal_agg = np.stack([aggregate(v) for v in gal_views])
        for q, truth in [(o, o.tree_id) for o in known] + [(o, None) for o in new]:
            qv = l2_normalize(np.stack([emb_of[p] for p in q.paths]))
            vs = qv @ gal_agg.T
            if score_mode == "aggregate":
                s = gal_agg @ aggregate(qv)
            elif score_mode == "max_pair":
                s = np.array([float((qv @ gv.T).max()) for gv in gal_views])
            else:
                raise ValueError(score_mode)
            rank = None
            if truth is not None:
                order = np.argsort(-s)
                rank = int(np.nonzero(np.asarray(tids)[order] == truth)[0][0]) + 1
            out.append(QueryScores(truth, tids, s, vs, q, rank))
    return out


def genuine_impostor(qs: list[QueryScores]) -> tuple[np.ndarray, np.ndarray]:
    """Genuine: score of the true tree. Impostor: best score of any wrong tree (per query)."""
    gen, imp = [], []
    for q in qs:
        if q.truth is not None:
            i = q.tree_ids.index(q.truth)
            gen.append(q.scores[i])
            others = np.delete(q.scores, i)
            if len(others):
                imp.append(others.max())
        else:
            imp.append(q.scores.max())
    return np.asarray(gen), np.asarray(imp)


def decide_global(qs: list[QueryScores], threshold: float) -> tuple[list[str | None], list[str | None]]:
    pred, truth = [], []
    for q in qs:
        j = int(np.argmax(q.scores))
        pred.append(q.tree_ids[j] if q.scores[j] >= threshold else None)
        truth.append(q.truth)
    return pred, truth


def closed_set_topk(qs: list[QueryScores], ks=(1, 5)) -> dict[str, float]:
    ranks = [q.rank for q in qs if q.truth is not None]
    return {f"top{k}": float(np.mean([r <= k for r in ranks])) for k in ks} | {
        "mean_rank": float(np.mean(ranks)), "n_known_queries": len(ranks)}


def build_observations(recs, tree_ids: set[str], species: str | None, views: int, seed: int) -> list[Observation]:
    sel = [r for r in recs if r.tree_id in tree_ids and (species is None or r.species == species)]
    return make_observations(sel, views, seed)


def all_pairs(qs: list[QueryScores]) -> tuple[np.ndarray, np.ndarray]:
    """Genuine vs EVERY wrong-tree score (standard verification ROC), not just the best wrong one."""
    gen, imp = [], []
    for q in qs:
        for j, t in enumerate(q.tree_ids):
            (gen if t == q.truth else imp).append(q.scores[j])
    return np.asarray(gen), np.asarray(imp)
