"""Deterministic image preprocessing shared by training-time evaluation and inference.

One decode per view: callers pass an already-decoded RGB uint8 array, and the
same array is reused for quality checks, local features and the network input.
"""

from __future__ import annotations

import cv2
import numpy as np

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


DECODE_MIN_SIDE = 640  # enough for quality checks (512 px), keypoints (640 px) and the network (322 px)


def decode_image(data: bytes, min_side: int | None = DECODE_MIN_SIDE) -> np.ndarray:
    """JPEG/PNG bytes -> RGB uint8 (H, W, 3), EXIF-oriented.

    For JPEGs, ``min_side`` lets libjpeg decode directly at 1/2, 1/4 or 1/8 scale
    (DCT scaling, Pillow ``draft``) while keeping the short side >= min_side.
    A 12 MP phone photo then decodes several times faster (E-efficiency), and
    the result matches the reduced-resolution decode used to build the training
    cache. ``min_side=None`` decodes at full resolution.
    """
    import io

    from PIL import Image, ImageOps

    im = Image.open(io.BytesIO(data))
    if min_side is not None and im.format == "JPEG":
        w, h = im.size
        scale = 1
        while scale < 8 and min(w, h) // (scale * 2) >= min_side:
            scale *= 2
        if scale > 1:
            im.draft("RGB", (w // scale, h // scale))
    return np.asarray(ImageOps.exif_transpose(im).convert("RGB"))


def resize_short_center_crop(rgb: np.ndarray, size: int) -> np.ndarray:
    """Resize so the short side == size (area interpolation), then centre-crop size x size."""
    h, w = rgb.shape[:2]
    s = size / min(h, w)
    nh, nw = max(size, int(round(h * s))), max(size, int(round(w * s)))
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    r = cv2.resize(rgb, (nw, nh), interpolation=interp)
    y0, x0 = (nh - size) // 2, (nw - size) // 2
    return r[y0:y0 + size, x0:x0 + size]


def to_network_input(rgb: np.ndarray, size: int) -> np.ndarray:
    """RGB uint8 -> float32 (3, size, size), ImageNet-normalised (NCHW without batch)."""
    x = resize_short_center_crop(rgb, size).astype(np.float32) / 255.0
    x = (x - IMAGENET_MEAN) / IMAGENET_STD
    return np.ascontiguousarray(x.transpose(2, 0, 1))
