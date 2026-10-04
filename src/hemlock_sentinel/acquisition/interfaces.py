"""Hardware abstraction layer.

The pipeline only talks to these protocols. Concrete providers:

* Camera:       PhoneUploadCamera (browser getUserMedia via the web app),
                FileCamera (dataset replay), and, on a Pi, a Picamera2 adapter
                (docs/deployment.md) — all yield RGB uint8 arrays.
* DepthProvider: RGB-D camera (e.g. RealSense D4xx), phone depth (ARKit /
                ARCore depth uploaded with the photo), stereo, SimulatedDepth.
* GPS / EnvironmentalSensors / Storage / ModelRuntime: likewise.

Mocks live in acquisition/mocks.py and are used by the tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass
class Frame:
    rgb: np.ndarray  # (H, W, 3) uint8, already EXIF-oriented
    timestamp: float
    encoded: bytes | None = None  # original JPEG bytes, stored as-is (no re-encode)
    heading_deg: float | None = None  # compass heading if the device reports it


@dataclass
class DepthFrame:
    depth_m: np.ndarray  # (H, W) float32 metres, 0 = invalid
    fx: float
    fy: float
    cx: float
    cy: float
    source: str  # "rgbd", "phone", "stereo", "simulated"
    # Expected depth noise model sigma(z) = a + b*z^2 (metres); used to set
    # comparison tolerances and to decide whether depth is usable at all.
    noise_a: float = 0.0
    noise_b: float = 0.0


@dataclass
class GeoFix:
    lat: float
    lon: float
    accuracy_m: float  # horizontal 1-sigma reported by the receiver
    altitude_m: float | None = None


@dataclass
class EnvReading:
    values: dict[str, float] = field(default_factory=dict)  # e.g. {"temp_c": 14.2, "rh": 81}


@runtime_checkable
class Camera(Protocol):
    def capture(self) -> Frame: ...


@runtime_checkable
class DepthProvider(Protocol):
    def available(self) -> bool: ...

    def capture_depth(self, frame: Frame) -> DepthFrame | None: ...


@runtime_checkable
class GPS(Protocol):
    def fix(self) -> GeoFix | None: ...


@runtime_checkable
class EnvironmentalSensors(Protocol):
    def read(self) -> EnvReading: ...


@runtime_checkable
class Storage(Protocol):
    def put(self, data: bytes, suffix: str) -> str: ...  # returns a content key

    def get(self, key: str) -> bytes: ...

    def path(self, key: str) -> str: ...


@runtime_checkable
class ModelRuntime(Protocol):
    """Runs the shared backbone: (N, 3, S, S) float32 -> (embeddings (N, D), species_logits (N, C))."""

    input_size: int
    embedding_dim: int

    def run(self, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...
