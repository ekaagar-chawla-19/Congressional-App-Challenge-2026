"""Global cosine retrieval over stored observation embeddings.

The gallery is small (hundreds to a few thousand trees per site), so an exact
brute-force matrix product over unit vectors is both the most accurate and the
cheapest option — no approximate index is needed. Embeddings are stored on
disk as float16 (4.3 KB per 2152-d observation; changes cosine by <1e-3,
tests/numerical). In RAM they are float32: numpy has no fast fp16 matmul, and
the first version (fp16 in RAM + per-query up-cast + np.maximum.at
scatter) took 40 ms for 400 observations; this version is benchmarked in
benchmarks/bench_retrieval.py and docs/experiments.md (E-efficiency).

A tree's score against a query is the max over that tree's stored observation
embeddings (not only a canonical mean), so a tree photographed in several
seasons still matches a query from any of them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .multiview import l2_normalize


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity between rows of a (N, D) and b (M, D) -> (N, M) in [-1, 1]."""
    a = l2_normalize(np.atleast_2d(a))
    b = l2_normalize(np.atleast_2d(b))
    return np.clip(a @ b.T, -1.0, 1.0)


@dataclass
class Candidate:
    tree_id: str
    score: float  # max cosine over the tree's observations
    rank: int


class EmbeddingIndex:
    """Exact cosine index: rows are observation embeddings labelled by tree_id."""

    def __init__(self, dim: int):
        self.dim = dim
        self._vecs = np.zeros((16, dim), dtype=np.float32)  # capacity-doubling buffer
        self._n = 0
        self._codes = np.zeros(16, dtype=np.int64)
        self._obs_ids: list[str] = []
        self._tree_names: list[str] = []
        self._tree_lookup: dict[str, int] = {}
        self._perm: np.ndarray | None = None  # rows sorted by tree code (lazy)
        self._starts: np.ndarray | None = None

    def __len__(self) -> int:
        return self._n

    @property
    def n_trees(self) -> int:
        return len(self._tree_names)

    def nbytes(self) -> int:
        return self._n * self.dim * 4

    def add(self, tree_id: str, embedding: np.ndarray, observation_id: str | None = None) -> None:
        self.add_many([tree_id], np.asarray(embedding)[None, :], [observation_id or f"obs-{self._n}"])

    def add_many(self, tree_ids: list[str], embeddings: np.ndarray, observation_ids: list[str] | None = None) -> None:
        e = l2_normalize(np.asarray(embeddings, dtype=np.float32))
        if e.ndim != 2 or e.shape[1] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {e.shape[-1]}")
        m = len(e)
        if self._n + m > len(self._vecs):
            cap = max(2 * len(self._vecs), self._n + m)
            self._vecs = np.resize(self._vecs, (cap, self.dim))
            self._codes = np.resize(self._codes, cap)
        for k, t in enumerate(tree_ids):
            if t not in self._tree_lookup:
                self._tree_lookup[t] = len(self._tree_names)
                self._tree_names.append(t)
            self._codes[self._n + k] = self._tree_lookup[t]
        self._vecs[self._n:self._n + m] = e
        self._obs_ids.extend(observation_ids or [f"obs-{self._n + i}" for i in range(m)])
        self._n += m
        self._perm = None

    def _grouping(self) -> tuple[np.ndarray, np.ndarray]:
        if self._perm is None:
            codes = self._codes[:self._n]
            self._perm = np.argsort(codes, kind="stable")
            self._starts = np.searchsorted(codes[self._perm], np.arange(self.n_trees))
        return self._perm, self._starts

    def tree_scores(self, queries: np.ndarray) -> np.ndarray:
        """(Q, D) queries -> (Q, n_trees) max-over-observations cosine."""
        q = l2_normalize(np.atleast_2d(np.asarray(queries, dtype=np.float32)))
        if self._n == 0:
            return np.zeros((q.shape[0], 0), np.float32)
        perm, starts = self._grouping()
        sims = q @ self._vecs[:self._n].T
        return np.clip(np.maximum.reduceat(sims[:, perm], starts, axis=1), -1.0, 1.0)

    def search(self, query: np.ndarray, k: int = 5) -> list[Candidate]:
        if self.n_trees == 0:
            return []
        scores = self.tree_scores(query)[0]
        order = np.argsort(-scores)[:k]
        return [Candidate(self._tree_names[i], float(scores[i]), r + 1) for r, i in enumerate(order)]

    def tree_names(self) -> list[str]:
        return list(self._tree_names)
