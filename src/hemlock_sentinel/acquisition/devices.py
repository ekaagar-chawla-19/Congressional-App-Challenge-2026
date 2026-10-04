"""Adapters for real handheld hardware (Raspberry Pi path).

STATUS: written against the vendors' documented Python APIs, but NOT exercised
on hardware in this repository (no device was available to the CI/dev
machine). Each import is lazy so the package works without the SDKs. Verify
on the device with ``python -m hemlock_sentinel.acquisition.devices`` before
field use (docs/deployment.md).
"""

from __future__ import annotations

import time

import numpy as np

from .interfaces import DepthFrame, Frame, GeoFix


class Picamera2Camera:
    """Raspberry Pi camera via picamera2 (libcamera)."""

    def __init__(self, size=(2028, 1520)):
        from picamera2 import Picamera2  # apt install python3-picamera2

        self.cam = Picamera2()
        self.cam.configure(self.cam.create_still_configuration(main={"size": size, "format": "RGB888"}))
        self.cam.start()

    def capture(self) -> Frame:
        # picamera2's "RGB888" is BGR byte order in memory; convert to RGB.
        arr = self.cam.capture_array("main")[:, :, ::-1].copy()
        return Frame(arr, time.time())


class RealSenseDepth:
    """Intel RealSense D4xx depth aligned to colour (pyrealsense2)."""

    def __init__(self, width=848, height=480, fps=15):
        import pyrealsense2 as rs

        self.rs = rs
        self.pipe = rs.pipeline()
        cfg = rs.config()
        cfg.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
        cfg.enable_stream(rs.stream.color, width, height, rs.format.rgb8, fps)
        prof = self.pipe.start(cfg)
        self.scale = prof.get_device().first_depth_sensor().get_depth_scale()
        self.align = rs.align(rs.stream.color)

    def available(self) -> bool:
        return True

    def capture_depth(self, frame: Frame | None = None) -> DepthFrame:
        frames = self.align.process(self.pipe.wait_for_frames())
        d = frames.get_depth_frame()
        intr = d.profile.as_video_stream_profile().intrinsics
        depth = np.asanyarray(d.get_data()).astype(np.float32) * self.scale
        # D4xx stereo: RMS error grows ~quadratically with distance; coarse default
        # from the <2 % at 2 m spec. Replace with a per-unit measurement.
        return DepthFrame(depth, intr.fx, intr.fy, intr.ppx, intr.ppy, "rgbd", 0.002, 0.005)


class GpsdGPS:
    """GPS via gpsd (USB/UART receiver)."""

    def __init__(self):
        from gps import WATCH_ENABLE, gps  # apt install python3-gps

        self.session = gps(mode=WATCH_ENABLE)

    def fix(self) -> GeoFix | None:
        for _ in range(10):
            r = self.session.next()
            if r.get("class") == "TPV" and "lat" in r:
                return GeoFix(r["lat"], r["lon"], float(r.get("eph", r.get("epx", 50.0))), r.get("alt"))
        return None


if __name__ == "__main__":  # pragma: no cover - hardware smoke test
    for cls in (Picamera2Camera, RealSenseDepth, GpsdGPS):
        try:
            dev = cls()
            out = dev.capture() if hasattr(dev, "capture") else (
                dev.capture_depth() if hasattr(dev, "capture_depth") else dev.fix())
            print(cls.__name__, "OK", type(out).__name__)
        except Exception as e:  # noqa: BLE001
            print(cls.__name__, "unavailable:", e)
