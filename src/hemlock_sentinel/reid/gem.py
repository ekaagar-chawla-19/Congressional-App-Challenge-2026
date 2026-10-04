"""Generalized-mean (GeM) pooling.

Radenović et al., "Fine-tuning CNN Image Retrieval with No Human Annotation"
(TPAMI 2018). p=1 is average pooling and p→∞ approaches max pooling; p is
learned. MiewID initialises p=3 and learns it (wbia_miew_id/models/model.py).
"""

from __future__ import annotations

import torch
from torch import nn


class GeM(nn.Module):
    def __init__(self, p: float = 3.0, eps: float = 1e-6, learnable: bool = True):
        super().__init__()
        p_tensor = torch.ones(1) * p
        if learnable:
            self.p = nn.Parameter(p_tensor)
        else:
            self.register_buffer("p", p_tensor)
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, C, H, W) -> (B, C). mean() over H, W instead of avg_pool2d with a
        # size taken from x.shape keeps the ONNX graph free of shape-dependent
        # kernel sizes.
        return x.clamp(min=self.eps).pow(self.p).mean(dim=(-2, -1)).pow(1.0 / self.p)

    def extra_repr(self) -> str:
        return f"p={float(self.p.detach()):.4f}, eps={self.eps}"
