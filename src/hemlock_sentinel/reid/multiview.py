"""Multi-view aggregation of per-view embeddings into one tree embedding.

Production: quality-weighted mean of L2-normalised view embeddings, then
re-normalised (numpy only, no parameters). Learned aggregators (attention
pooling, a small transformer over view tokens) are provided for the controlled
ablation in docs/experiments.md and are only kept if they beat the mean by a
margin that justifies their cost.
"""

from __future__ import annotations

import numpy as np


def l2_normalize(x: np.ndarray, axis: int = -1, eps: float = 1e-12) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return x / np.maximum(np.linalg.norm(x, axis=axis, keepdims=True), eps)


def aggregate_mean(view_embeddings: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    """(V, D) view embeddings -> (D,) unit-norm tree embedding."""
    v = np.asarray(view_embeddings, dtype=np.float32)
    if v.ndim != 2 or v.shape[0] == 0:
        raise ValueError("expected a non-empty (V, D) array")
    z = l2_normalize(v)
    if weights is None:
        w = np.ones(len(z), dtype=np.float32)
    else:
        w = np.asarray(weights, dtype=np.float32).reshape(-1)
        if w.shape[0] != z.shape[0]:
            raise ValueError("one weight per view required")
        if np.any(w < 0):
            raise ValueError("weights must be non-negative")
        if w.sum() <= 0:
            w = np.ones(len(z), dtype=np.float32)
    return l2_normalize((w[:, None] * z).sum(0))


# --------------------------------------------------------------------------
# Learned aggregators (torch; experiments only)
# --------------------------------------------------------------------------
try:  # pragma: no cover - torch is optional on the handheld
    import torch
    import torch.nn.functional as F
    from torch import nn

    class AttentionPool(nn.Module):
        """Per-view scalar attention: w_i = softmax(MLP(z_i)); out = sum w_i z_i."""

        def __init__(self, dim: int, hidden: int = 128):
            super().__init__()
            self.score = nn.Sequential(nn.Linear(dim, hidden), nn.Tanh(), nn.Linear(hidden, 1))

        def forward(self, views: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
            z = F.normalize(views, dim=-1)  # (B, V, D)
            s = self.score(z).squeeze(-1)
            if mask is not None:
                s = s.masked_fill(~mask, -1e9)
            w = s.softmax(dim=1)
            return F.normalize((w.unsqueeze(-1) * z).sum(1), dim=-1)

    class MultiViewTransformer(nn.Module):
        """Small transformer over view tokens with a learnable [AGG] token."""

        def __init__(self, dim: int, model_dim: int = 256, layers: int = 2, heads: int = 4):
            super().__init__()
            self.inp = nn.Linear(dim, model_dim)
            self.agg = nn.Parameter(torch.zeros(1, 1, model_dim))
            enc = nn.TransformerEncoderLayer(model_dim, heads, model_dim * 2, dropout=0.1, batch_first=True)
            self.enc = nn.TransformerEncoder(enc, layers)
            self.out = nn.Linear(model_dim, dim)

        def forward(self, views: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
            z = F.normalize(views, dim=-1)
            x = torch.cat([self.agg.expand(z.shape[0], -1, -1), self.inp(z)], dim=1)
            pad = None
            if mask is not None:
                pad = torch.cat([torch.zeros_like(mask[:, :1]), ~mask], dim=1)
            h = self.enc(x, src_key_padding_mask=pad)[:, 0]
            # Residual to the plain mean keeps the model from discarding the
            # strong mean baseline at initialisation.
            if mask is None:
                mean = z.mean(1)
            else:
                mean = (z * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True).clamp(min=1)
            return F.normalize(mean + self.out(h), dim=-1)
except ImportError:  # pragma: no cover
    pass
