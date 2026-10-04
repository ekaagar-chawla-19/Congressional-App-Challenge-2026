"""Shared builders for integration / end-to-end tests (mock model, bark-like images)."""

from __future__ import annotations

import time

import cv2
import numpy as np

from hemlock_sentinel.acquisition.interfaces import Frame
from hemlock_sentinel.acquisition.mocks import LocalFileStorage
from hemlock_sentinel.database.repository import TreeRepository
from hemlock_sentinel.pipeline.inference import HemlockSentinel, PipelineConfig
from hemlock_sentinel.pipeline.runtime import MockRuntime
from hemlock_sentinel.reid.calibration import Calibration
from hemlock_sentinel.species.labels import SPECIES

from .conftest import bark_like


def tree_view(tree_seed: int, view: int, jitter_seed: int = 0) -> np.ndarray:
    """Different regions of one large per-tree bark texture = the views of one tree.

    A capture session re-photographs the same regions with small camera jitter.
    """
    big = bark_like(tree_seed, 900, 1200)
    x0 = 40 + view * 260
    rng = np.random.default_rng(jitter_seed * 100 + view)
    dx, dy = rng.integers(-3, 4, 2)
    crop = big[100 + dy:100 + dy + 600, x0 + dx:x0 + dx + 400]
    return np.ascontiguousarray(crop)


def species_fn_factory(supported=True, confident=True):
    def fn(_x):
        logits = np.zeros(len(SPECIES), np.float32)
        if confident:
            logits[0 if supported else 1] = 8.0
        return logits
    return fn


def build(tmp_path, species_fn=None, cal: Calibration | None = None, **cfg):
    rt = MockRuntime(input_size=64, embedding_dim=128, species_fn=species_fn or species_fn_factory())
    repo = TreeRepository(tmp_path / "db.sqlite")
    storage = LocalFileStorage(tmp_path / "blobs")
    cal = cal or Calibration(species_threshold=0.6, global_threshold=0.8, match_threshold=0.5,
                             view_contradiction_margin=0.05, view_match_threshold=0.4)
    return HemlockSentinel(rt, repo, storage, cal, PipelineConfig(**cfg))


def capture(app: HemlockSentinel, images: list[np.ndarray]):
    views = []
    for i, img in enumerate(images):
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        views.append(app.process_view(Frame(img, time.time(), encoded=buf.tobytes()), i, previous=views))
    return views
