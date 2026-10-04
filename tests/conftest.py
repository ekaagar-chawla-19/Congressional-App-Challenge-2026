import numpy as np
import pytest

try:
    import torch

    torch.set_num_threads(1)
except ImportError:  # pragma: no cover
    pass


def bark_like(seed: int, h: int = 480, w: int = 360) -> np.ndarray:
    """Procedural bark-like RGB texture: vertical fissures + noise, unique per seed."""
    rng = np.random.default_rng(seed)
    base = rng.normal(0, 1, (h // 8, w // 4))
    import cv2

    tex = cv2.resize(base, (w, h), interpolation=cv2.INTER_CUBIC)
    tex += 0.6 * cv2.resize(rng.normal(0, 1, (h // 2, w // 2)), (w, h))
    fiss = np.zeros((h, w))
    for _ in range(25):
        x = rng.integers(0, w)
        y0, y1 = sorted(rng.integers(0, h, 2))
        fiss[y0:y1, max(0, x - 2):x + 2] -= 2.0
    tex = tex + cv2.GaussianBlur(fiss, (3, 3), 0) + 1.5 * rng.normal(0, 1, (h, w))
    lo, hi = np.percentile(tex, [2, 98])
    tex = np.clip((tex - lo) / (hi - lo), 0, 1)
    rgb = np.stack([30 + 170 * tex, 25 + 140 * tex, 20 + 110 * tex], -1)
    return np.clip(rgb, 0, 255).astype(np.uint8)


@pytest.fixture
def bark():
    return bark_like
