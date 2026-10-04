"""Metric-learning objectives.

Production objective: sub-center ArcFace with dynamic (class-frequency) margins,
as implemented in MiewID (wbia_miew_id/models/heads.py, train.py):

* Sub-center ArcFace (Deng et al., ECCV 2020): each class owns K weight
  vectors; the class cosine is the max over its K sub-centres, which lets noisy
  or multi-modal classes (for us: bark vs branch vs canopy views of one tree)
  occupy several clusters.
* Dynamic margins (MiewID, after the Google Landmark 2020 winning solution):
  ``tmp = sqrt(1/sqrt(n_c))`` min-max scaled into ``[m_min, m_max]``, so classes
  with fewer images get larger margins.
* ArcFace logit for the target: ``cos(theta + m)``, with the standard fallback
  ``cos(theta) - m*sin(m)`` when ``theta + m > pi`` (non-monotonic region).

Comparison objectives (experiments only, not production): standard ArcFace
(K=1, fixed margin), supervised contrastive (Khosla et al., NeurIPS 2020) and
batch-hard triplet (Hermans et al., 2017).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn


def dynamic_margins(class_counts: Sequence[int], m_min: float = 0.2, m_max: float = 0.5) -> np.ndarray:
    """MiewID's per-class margins from class frequency.

    MiewID divides by ``tmp.max() - tmp.min()`` which is 0/0 = NaN when all
    classes have the same count (common in curated datasets). We return
    ``m_max`` for every class in that case (regression test
    tests/unit/test_losses.py::test_dynamic_margins_equal_counts).
    """
    counts = np.asarray(class_counts, dtype=np.float64)
    if counts.ndim != 1 or len(counts) == 0 or np.any(counts <= 0):
        raise ValueError("class_counts must be a non-empty 1-D array of positive counts")
    tmp = np.sqrt(1.0 / np.sqrt(counts))
    span = tmp.max() - tmp.min()
    if span < 1e-12:
        return np.full_like(tmp, m_max)
    return (tmp - tmp.min()) / span * (m_max - m_min) + m_min


class SubCenterArcFace(nn.Module):
    """Sub-center ArcFace with per-class margins. Returns the CE loss.

    ``k=1`` with constant margins is the standard ArcFace baseline.
    """

    def __init__(self, embedding_dim: int, n_classes: int, k: int = 3, s: float = 30.0,
                 margins: Sequence[float] | float = 0.5):
        super().__init__()
        self.n_classes = n_classes
        self.k = k
        self.s = s
        self.weight = nn.Parameter(torch.empty(n_classes * k, embedding_dim))
        stdv = 1.0 / math.sqrt(embedding_dim)
        nn.init.uniform_(self.weight, -stdv, stdv)  # as MiewID ArcMarginProduct_subcenter
        if isinstance(margins, (int, float)):
            margins = [float(margins)] * n_classes
        m = torch.as_tensor(np.asarray(margins, dtype=np.float32))
        if m.shape != (n_classes,):
            raise ValueError(f"margins must have shape ({n_classes},), got {tuple(m.shape)}")
        self.register_buffer("margins", m)

    def cosine(self, emb: torch.Tensor) -> torch.Tensor:
        cos_all = F.linear(F.normalize(emb.float(), dim=1), F.normalize(self.weight, dim=1))
        return cos_all.view(-1, self.n_classes, self.k).max(dim=2).values

    def logits(self, emb: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        cos = self.cosine(emb).clamp(-1.0, 1.0)
        m = self.margins[labels].unsqueeze(1)
        # Clamp before sqrt: d/dx sqrt(x) is infinite at x=0 (cos = ±1), which
        # MiewID's implementation does not guard against.
        sin = torch.sqrt((1.0 - cos * cos).clamp(min=1e-7))
        phi = cos * torch.cos(m) - sin * torch.sin(m)
        th = torch.cos(math.pi - m)
        mm = torch.sin(math.pi - m) * m
        phi = torch.where(cos > th, phi, cos - mm)
        one_hot = F.one_hot(labels, self.n_classes).to(cos.dtype)
        return self.s * (one_hot * phi + (1.0 - one_hot) * cos)

    def forward(self, emb: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        return F.cross_entropy(self.logits(emb, labels), labels)


class SupConLoss(nn.Module):
    """Supervised contrastive loss (Khosla et al. 2020), L_out variant."""

    def __init__(self, temperature: float = 0.1):
        super().__init__()
        self.t = temperature

    def forward(self, emb: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        z = F.normalize(emb.float(), dim=1)
        sim = z @ z.T / self.t
        n = z.shape[0]
        self_mask = torch.eye(n, dtype=torch.bool, device=z.device)
        pos = (labels[:, None] == labels[None, :]) & ~self_mask
        sim = sim.masked_fill(self_mask, -1e9)
        log_prob = sim - torch.logsumexp(sim, dim=1, keepdim=True)
        n_pos = pos.sum(1)
        valid = n_pos > 0
        if not valid.any():
            return emb.sum() * 0.0
        mean_log_pos = (log_prob * pos).sum(1)[valid] / n_pos[valid]
        return -mean_log_pos.mean()


class BatchHardTripletLoss(nn.Module):
    """Batch-hard triplet loss on cosine distance (Hermans et al. 2017)."""

    def __init__(self, margin: float = 0.2):
        super().__init__()
        self.margin = margin

    def forward(self, emb: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        z = F.normalize(emb.float(), dim=1)
        d = 1.0 - z @ z.T
        same = labels[:, None] == labels[None, :]
        eye = torch.eye(len(labels), dtype=torch.bool, device=z.device)
        pos_mask = same & ~eye
        valid = pos_mask.any(1) & (~same).any(1)
        if not valid.any():
            return emb.sum() * 0.0
        hardest_pos = (d * pos_mask).max(1).values
        hardest_neg = d.masked_fill(same, float("inf")).min(1).values
        return F.relu(hardest_pos - hardest_neg + self.margin)[valid].mean()


def build_loss(name: str, embedding_dim: int, n_classes: int, class_counts=None, **kw) -> nn.Module:
    name = name.lower()
    if name == "subcenter_arcface":
        margins = dynamic_margins(class_counts, kw.get("m_min", 0.2), kw.get("m_max", 0.5)) \
            if class_counts is not None else kw.get("m_max", 0.5)
        return SubCenterArcFace(embedding_dim, n_classes, k=kw.get("k", 3), s=kw.get("s", 30.0), margins=margins)
    if name == "arcface":
        return SubCenterArcFace(embedding_dim, n_classes, k=1, s=kw.get("s", 30.0), margins=kw.get("m_max", 0.5))
    if name == "supcon":
        return SupConLoss(kw.get("temperature", 0.1))
    if name == "triplet":
        return BatchHardTripletLoss(kw.get("margin", 0.2))
    raise ValueError(f"unknown loss {name!r}")
