"""Individual-tree embedding network: backbone -> GeM -> BatchNorm -> embedding.

This follows MiewID's ``MiewIdNet`` with ``use_fc=False`` (their default and the
configuration of the released msv3 checkpoint): the embedding is the
BatchNorm-ed GeM-pooled backbone feature, so its dimension equals the backbone
width (2152 for efficientnetv2_rw_m). L2 normalisation happens at retrieval
time, not inside the network, so the margin loss sees the same vector that is
stored.

A small species head shares the backbone so that one forward pass per view
serves both species gating and re-identification (no second network on the
handheld). It reads the L2-normalised embedding.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F
from torch import nn

from .backbone import PRIMARY_BACKBONE, Backbone
from .gem import GeM


@dataclass
class ReIDConfig:
    backbone: str = PRIMARY_BACKBONE
    pretrained: bool = True
    image_size: int = 320
    gem_p: float = 3.0
    n_species: int = 0  # 0 -> no species head


class ReIDNet(nn.Module):
    def __init__(self, cfg: ReIDConfig):
        super().__init__()
        self.cfg = cfg
        self.backbone = Backbone(cfg.backbone, pretrained=cfg.pretrained)
        self.pool = GeM(p=cfg.gem_p)
        self.bn = nn.BatchNorm1d(self.backbone.num_features)
        self.embedding_dim = self.backbone.num_features
        self.species_head = nn.Linear(self.embedding_dim, cfg.n_species) if cfg.n_species > 0 else None

    def pooled(self, x: torch.Tensor) -> torch.Tensor:
        return self.pool(self.backbone(x))

    def embed(self, x: torch.Tensor) -> torch.Tensor:
        """Raw (un-normalised) embedding used by the training losses."""
        return self.bn(self.pooled(x))

    def forward(self, x: torch.Tensor):
        emb = self.embed(x)
        if self.species_head is None:
            return emb
        return emb, self.species_head(F.normalize(emb, dim=1))


class EmbeddingHead(nn.Module):
    """GeM + BN on top of a cached feature map; used when the backbone trunk is frozen."""

    def __init__(self, dim: int, gem_p: float = 3.0):
        super().__init__()
        self.pool = GeM(p=gem_p)
        self.bn = nn.BatchNorm1d(dim)

    def forward(self, fmap: torch.Tensor) -> torch.Tensor:
        return self.bn(self.pool(fmap))
