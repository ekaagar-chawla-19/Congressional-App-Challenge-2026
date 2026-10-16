"""Privacy: blur faces that accidentally appear in tree photos before storage.

Uses OpenCV's YuNet face detector (cv2.FaceDetectorYN, 227 KB ONNX model,
MIT, models/third_party/). OpenCV 5 removed the Haar-cascade API, and YuNet
is both smaller to ship than a cascade set and more accurate. It runs at a
fixed 640 px analysis size (a few ms on CPU).

This is a mitigation, not a guarantee. Policy (docs/architecture.md): trees
are the only subject; no user identity is stored with observations; GPS is
stored at the precision the receiver reports. If the detector model is
missing, the pipeline logs a warning and records ``faces_blurred = -1`` so
unscreened images are identifiable later.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)
_FACE = Path("models/third_party/face_detection_yunet_2023mar.onnx")
MODEL_PATH = Path(os.environ.get("HEMLOCK_FACE_MODEL") or next(
    (b / _FACE for b in (Path(__file__).resolve().parents[3], Path.cwd(), Path("/app")) if (b / _FACE).exists()),
    Path(__file__).resolve().parents[3] / _FACE))
_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        if not MODEL_PATH.exists():
            log.warning("face detector model missing at %s; face blurring disabled", MODEL_PATH)
            _detector = False
        else:
            _detector = cv2.FaceDetectorYN.create(str(MODEL_PATH), "", (320, 320), 0.8, 0.3, 50)
    return _detector


def detect_faces(rgb: np.ndarray, side: int = 640) -> list[tuple[int, int, int, int]] | None:
    det = _get_detector()
    if det is False:
        return None
    h, w = rgb.shape[:2]
    s = min(1.0, side / max(h, w))
    small = cv2.resize(rgb, (int(w * s), int(h * s))) if s < 1 else rgb
    det.setInputSize((small.shape[1], small.shape[0]))
    _, faces = det.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
    if faces is None:
        return []
    return [tuple(int(v / s) for v in f[:4]) for f in faces]


def blur_faces(rgb: np.ndarray) -> tuple[np.ndarray, int]:
    """Returns (image, n_faces_blurred); n = -1 if the detector is unavailable."""
    boxes = detect_faces(rgb)
    if boxes is None:
        return rgb, -1
    if not boxes:
        return rgb, 0
    out = rgb.copy()
    for x, y, w, h in boxes:
        pad = int(0.25 * max(w, h))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(out.shape[1], x + w + pad), min(out.shape[0], y + h + pad)
        if x1 <= x0 or y1 <= y0:
            continue
        roi = out[y0:y1, x0:x1]
        k = max(31, (max(roi.shape[:2]) // 3) | 1)
        out[y0:y1, x0:x1] = cv2.GaussianBlur(roi, (k, k), 0)
    return out, len(boxes)
