"""In-memory retrieval index kept in sync with the repository.

Loaded lazily once per species and updated incrementally on every new
observation, so a capture never triggers a full reload from disk.
"""

from __future__ import annotations

import numpy as np

from ..reid.retrieval import EmbeddingIndex
from .repository import TreeRepository


class IndexCache:
    def __init__(self, repo: TreeRepository, dim: int):
        self.repo = repo
        self.dim = dim
        self._by_species: dict[str, EmbeddingIndex] = {}

    def get(self, species: str) -> EmbeddingIndex:
        if species not in self._by_species:
            idx = EmbeddingIndex(self.dim)
            tids, oids, emb = self.repo.gallery(species)
            if tids:
                idx.add_many(tids, emb, oids)
            self._by_species[species] = idx
        return self._by_species[species]

    def add(self, species: str, tree_id: str, embedding: np.ndarray, observation_id: str) -> None:
        self.get(species).add(tree_id, embedding, observation_id)

    def invalidate(self, species: str | None = None) -> None:
        if species is None:
            self._by_species.clear()
        else:
            self._by_species.pop(species, None)
