"""Mock / simulated hardware providers (tests, demos, and dataset replay).

SimulatedDepth renders a synthetic trunk. It exists to test the depth code
path and to study how sensor noise affects trunk-profile matching; results on
it are labelled SYNTHETIC everywhere and are not evidence about real hemlocks.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .interfaces import DepthFrame, EnvReading, Frame, GeoFix


class FileCamera:
    """Replays image files (dataset evaluation, offline tests)."""

    def __init__(self, paths: list[str]):
        self.paths = list(paths)
        self._i = 0

    def capture(self) -> Frame:
        from ..preprocessing import decode_image

        p = self.paths[self._i % len(self.paths)]
        self._i += 1
        data = Path(p).read_bytes()
        return Frame(decode_image(data), time.time(), encoded=data)


class ArrayCamera:
    def __init__(self, images: list[np.ndarray]):
        self.images = images
        self._i = 0

    def capture(self) -> Frame:
        img = self.images[self._i % len(self.images)]
        self._i += 1
        return Frame(img, time.time())


class NoDepth:
    def available(self) -> bool:
        return False

    def capture_depth(self, frame: Frame) -> DepthFrame | None:
        return None


@dataclass
class TrunkModel:
    """Synthetic stem: diameter(h) = dbh * taper(h) + per-tree irregularity, plus lean."""

    dbh_m: float
    taper_per_m: float
    irregularity: np.ndarray  # (n,) smooth bumps in metres along height
    lean: float

    @classmethod
    def random(cls, seed: int) -> "TrunkModel":
        r = np.random.default_rng(seed)
        bumps = np.convolve(r.normal(0, 0.012, 60), np.ones(5) / 5, mode="same")
        return cls(dbh_m=float(r.uniform(0.15, 0.6)), taper_per_m=float(r.uniform(0.01, 0.04)),
                   irregularity=bumps, lean=float(r.normal(0, 0.03)))

    def diameter(self, h: np.ndarray) -> np.ndarray:
        idx = np.clip((h / 0.05).astype(int), 0, len(self.irregularity) - 1)
        return np.maximum(self.dbh_m - self.taper_per_m * (h - 1.3) + self.irregularity[idx], 0.05)


class SimulatedDepth:
    """Renders a depth map of a TrunkModel seen from ``distance_m``.

    Noise model sigma(z) = a + b z^2 (stereo-style quadratic growth). Default
    b=0.005 is ~2 % at 2 m, matching Intel's D435 accuracy spec (<2 % at 2 m);
    it is a parameter, not a measured property of any particular device.
    """

    def __init__(self, trunk: TrunkModel, distance_m: float = 1.5, size=(240, 180), fov_deg: float = 60.0,
                 noise_a: float = 0.002, noise_b: float = 0.005, height_offset_m: float = 0.0, seed: int = 0):
        self.trunk = trunk
        self.distance = distance_m
        self.h, self.w = size
        self.f = (self.w / 2) / np.tan(np.radians(fov_deg) / 2)
        self.noise_a, self.noise_b = noise_a, noise_b
        self.height_offset = height_offset_m
        self.rng = np.random.default_rng(seed)

    def available(self) -> bool:
        return True

    def capture_depth(self, frame: Frame | None = None) -> DepthFrame:
        h, w, f = self.h, self.w, self.f
        cx, cy = w / 2, h / 2
        depth = np.zeros((h, w), np.float32)
        cam_h = 1.3 + self.height_offset  # camera height above stem base
        vs = np.arange(h)
        us = np.arange(w)
        for v in vs:
            # height of the ray at the trunk distance
            y = -(v - cy) / f * self.distance + cam_h
            if y < 0:
                continue
            r = self.trunk.diameter(np.array([y]))[0] / 2
            xc = self.trunk.lean * y
            x = (us - cx) / f  # ray direction x/z
            # intersect ray (x*z, z) with circle centred (xc, distance) radius r
            a = x * x + 1
            b = -2 * (xc * x + self.distance)
            c = xc * xc + self.distance ** 2 - r * r
            disc = b * b - 4 * a * c
            hit = disc >= 0
            z = (-b - np.sqrt(np.where(hit, disc, 0))) / (2 * a)
            depth[v, hit] = z[hit]
        valid = depth > 0
        sigma = self.noise_a + self.noise_b * depth ** 2
        depth[valid] += self.rng.normal(0, 1, valid.sum()) * sigma[valid]
        return DepthFrame(depth, f, f, cx, cy, "simulated", self.noise_a, self.noise_b)


class FixedGPS:
    def __init__(self, lat: float, lon: float, accuracy_m: float = 8.0):
        self._fix = GeoFix(lat, lon, accuracy_m)

    def fix(self) -> GeoFix | None:
        return self._fix


class NoGPS:
    def fix(self) -> GeoFix | None:
        return None


class NullSensors:
    def read(self) -> EnvReading:
        return EnvReading({})


class LocalFileStorage:
    """Content-addressed blob store: identical bytes are stored once."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes, suffix: str) -> str:
        key = hashlib.sha256(data).hexdigest() + suffix
        p = self.root / key[:2] / key
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
        return key

    def get(self, key: str) -> bytes:
        return (self.root / key[:2] / key).read_bytes()

    def path(self, key: str) -> str:
        return str(self.root / key[:2] / key)
