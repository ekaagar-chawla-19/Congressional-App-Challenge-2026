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


class _ViTTail(nn.Module):
    def __init__(self, blocks, norm, n_prefix: int):
        super().__init__()
        self.blocks, self.norm, self.n_prefix = blocks, norm, n_prefix

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        x = self.norm(self.blocks(tokens))[:, self.n_prefix:, :]
        side = int(round(x.shape[1] ** 0.5))
        return x.transpose(1, 2).reshape(x.shape[0], -1, side, side)


def trunk_tail(name: str, pretrained: bool = True, frozen: int | None = None, **timm_kwargs):
    """Split a timm backbone into a frozen trunk (cached once) and a trainable tail.

    Returns (trunk: nn.Module, tail: nn.Module -> (B, C, H, W) fmap, num_features, frozen).
    Used for CPU-budget fine-tuning (training/reid/cache_trunk.py, train_tail.py).
    """
    m = timm.create_model(name, pretrained=pretrained, num_classes=0, global_pool="", **timm_kwargs)
    if name.startswith("efficientnetv2"):
        k = 5 if frozen is None else frozen
        trunk = nn.Sequential(m.conv_stem, m.bn1, *m.blocks[:k])
        tail = nn.Sequential(m.blocks[k:], m.conv_head, m.bn2)
    elif "dinov2" in name or name.startswith("vit"):
        k = 8 if frozen is None else frozen

        class _Trunk(nn.Module):
            def __init__(self, vit, k):
                super().__init__()
                self.vit, self.k = vit, k

            def forward(self, x):
                v = self.vit
                x = v.norm_pre(v.patch_drop(v._pos_embed(v.patch_embed(x))))
                for b in v.blocks[: self.k]:
                    x = b(x)
                return x

        trunk = _Trunk(m, k)
        tail = _ViTTail(m.blocks[k:], m.norm, getattr(m, "num_prefix_tokens", 1))
    else:
        raise ValueError(f"no trunk/tail split defined for {name}")
    return trunk, tail, int(m.num_features), k


def last_block_split(name: str, pretrained: bool = True, **timm_kwargs):
    """For controlled ablations: (prefix, last) where prefix maps the trunk_tail()
    cache to the input of the LAST block, and last = last block + final layers.

    EfficientNetV2-M: prefix = blocks[5][:-1]; last = blocks[5][-1] + conv_head + bn2 (2.3 M params).
    DINOv2-S/14:      prefix = blocks[8:11];   last = blocks[11] + norm, tokens -> fmap (1.8 M params).
    """
    m = timm.create_model(name, pretrained=pretrained, num_classes=0, global_pool="", **timm_kwargs)
    if name.startswith("efficientnetv2"):
        prefix = nn.Sequential(*m.blocks[5][:-1])
        last = nn.Sequential(m.blocks[5][-1:], m.conv_head, m.bn2)
    elif "dinov2" in name or name.startswith("vit"):
        prefix = nn.Sequential(*m.blocks[8:-1])
        last = _ViTTail(m.blocks[-1:], m.norm, getattr(m, "num_prefix_tokens", 1))
    else:
        raise ValueError(name)
    return prefix, last, int(m.num_features)
