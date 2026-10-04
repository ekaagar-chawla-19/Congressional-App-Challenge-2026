"""Backbone construction (timm).

Primary backbone: ``efficientnetv2_rw_m`` — the exact timm model MiewID uses
(wbia_miew_id/configs/default_config.yaml), ImageNet-1k weights tag
``agc_in1k`` (Apache-2.0). Other names are accepted only for controlled
comparison experiments (docs/experiments.md); the production system keeps one.
"""

from __future__ import annotations

import timm
import torch
from torch import nn

PRIMARY_BACKBONE = "efficientnetv2_rw_m"


class Backbone(nn.Module):
    """Wraps a timm model and returns a (B, C, H, W) feature map."""

    def __init__(self, name: str = PRIMARY_BACKBONE, pretrained: bool = True, **timm_kwargs):
        super().__init__()
        self.name = name
        self.model = timm.create_model(name, pretrained=pretrained, num_classes=0, global_pool="", **timm_kwargs)
        self.num_features = int(self.model.num_features)
        cfg = self.model.pretrained_cfg
        self.mean = tuple(cfg.get("mean", (0.485, 0.456, 0.406)))
        self.std = tuple(cfg.get("std", (0.229, 0.224, 0.225)))
        # Transformers (Swin / DINOv2 ViT) return token layouts; we convert to NCHW.
        self._is_vit = hasattr(self.model, "cls_token") and self.model.cls_token is not None
        self._nhwc = name.startswith("swin")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        f = self.model.forward_features(x)
        if self._is_vit:
            prefix = getattr(self.model, "num_prefix_tokens", 1)
            tokens = f[:, prefix:, :]
            n = tokens.shape[1]
            side = int(round(n**0.5))
            return tokens.transpose(1, 2).reshape(f.shape[0], -1, side, side)
        if self._nhwc:
            return f.permute(0, 3, 1, 2)
        return f
