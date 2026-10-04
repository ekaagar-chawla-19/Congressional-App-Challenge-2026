"""Global cosine retrieval over stored observation embeddings.

The gallery is small (hundreds to a few thousand trees per site), so an exact
brute-force matrix product over unit vectors is both the most accurate and the
cheapest option. Vectors are stored as float16 (4.3 KB per 2152-d observation,
43 MB for 10k observations instead of 86 MB in float32) and the product is
computed in float32 blocks. float16 storage changes cosine scores by <1e-3
(tests/numerical). Measured in benchmarks/bench_retrieval.py.

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

    def __init__(self, dim: int, dtype=np.float16, block: int = 4096):
        self.dim = dim
        self.dtype = dtype
        self.block = block
        self._vecs = np.zeros((0, dim), dtype=dtype)
        self._tree_ids: list[str] = []
        self._obs_ids: list[str] = []
        self._tree_codes = np.zeros(0, dtype=np.int64)
        self._tree_names: list[str] = []
        self._tree_lookup: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._tree_ids)

    @property
    def n_trees(self) -> int:
        return len(self._tree_names)

    def add(self, tree_id: str, embedding: np.ndarray, observation_id: str | None = None) -> None:
        self.add_many([tree_id], np.asarray(embedding)[None, :], [observation_id or f"obs-{len(self)}"])

    def add_many(self, tree_ids: list[str], embeddings: np.ndarray, observation_ids: list[str] | None = None) -> None:
        e = l2_normalize(np.asarray(embeddings, dtype=np.float32))
        if e.shape[1] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {e.shape[1]}")
        codes = []
        for t in tree_ids:
            if t not in self._tree_lookup:
                self._tree_lookup[t] = len(self._tree_names)
                self._tree_names.append(t)
            codes.append(self._tree_lookup[t])
        self._vecs = np.concatenate([self._vecs, e.astype(self.dtype)], axis=0)
        self._tree_ids.extend(tree_ids)
        self._obs_ids.extend(observation_ids or [f"obs-{len(self._obs_ids) + i}" for i in range(len(tree_ids))])
        self._tree_codes = np.concatenate([self._tree_codes, np.asarray(codes, dtype=np.int64)])

    def tree_scores(self, queries: np.ndarray) -> np.ndarray:
        """(Q, D) queries -> (Q, n_trees) max-over-observations cosine."""
        q = l2_normalize(np.atleast_2d(np.asarray(queries, dtype=np.float32)))
        out = np.full((q.shape[0], self.n_trees), -1.0, dtype=np.float32)
        for start in range(0, len(self), self.block):
            sims = q @ self._vecs[start:start + self.block].astype(np.float32).T
            codes = self._tree_codes[start:start + self.block]
            # scatter-max of observation sims into their tree column
            out_t = out.T  # view: (n_trees, Q)
            np.maximum.at(out_t, codes, sims.T)
        return np.clip(out, -1.0, 1.0)

    def search(self, query: np.ndarray, k: int = 5) -> list[Candidate]:
        if self.n_trees == 0:
            return []
        scores = self.tree_scores(query)[0]
        order = np.argsort(-scores)[:k]
        return [Candidate(self._tree_names[i], float(scores[i]), r + 1) for r, i in enumerate(order)]

    def tree_names(self) -> list[str]:
        return list(self._tree_names)
