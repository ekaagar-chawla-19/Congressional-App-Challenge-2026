"""ModelRuntime implementations: ONNX Runtime (edge default), Torch (dev), Mock (tests).

All runtimes take a (N, 3, S, S) float32 batch from preprocessing.to_network_input
and return (embeddings (N, D) raw BN outputs, species logits (N, C)). The model
is loaded once per process and reused for every view.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class OnnxRuntime:
    def __init__(self, model_path: str | Path, threads: int = 4):
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(model_path), so, providers=["CPUExecutionProvider"])
        meta = json.loads(Path(model_path).with_suffix(".json").read_text())
        self.input_size = int(meta["image_size"])
        self.embedding_dim = int(meta["embedding_dim"])
        self.species_labels = list(meta["species_labels"])
        self.version = meta.get("version", Path(model_path).stem)
        self.backbone = meta.get("backbone")
        self.model_path = Path(model_path)

    def run(self, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        emb, logits = self.session.run(None, {"images": np.ascontiguousarray(batch, dtype=np.float32)})
        return emb, logits


class GammaRuntime:
    """Model gamma: the RTX 3060 BarkNet ViT-S/14 448 px checkpoint, exported unchanged (scripts/export_gamma.py).

    It has no species head (species_labels is empty) and needs its own preprocessing, so it implements
    ``embed_rgb`` (one decoded photo -> embedding, None) instead of being fed to_network_input batches:
    short side to 640, five 448 px crops (centre + corners), mean of the L2-normalised crop embeddings.
    This is the evaluation protocol the checkpoint's reported numbers were measured with.
    """

    def __init__(self, model_path: str | Path, threads: int = 4):
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(model_path), so, providers=["CPUExecutionProvider"])
        meta = json.loads(Path(model_path).with_suffix(".json").read_text())
        self.input_size = int(meta["image_size"])
        self.resize = int(meta.get("resize_short_side", 640))
        self.embedding_dim = int(meta["embedding_dim"])
        self.species_labels: list[str] = list(meta.get("species_labels", []))
        self.version = meta.get("version", Path(model_path).stem)
        self.backbone = meta.get("backbone")
        self.model_path = Path(model_path)

    def crops(self, rgb: np.ndarray) -> np.ndarray:
        import cv2

        from ..preprocessing import IMAGENET_MEAN, IMAGENET_STD

        h, w = rgb.shape[:2]
        s = self.resize / min(h, w)
        img = cv2.resize(rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        h, w = img.shape[:2]
        c = self.input_size
        pos = [((h - c) // 2, (w - c) // 2), (0, 0), (0, w - c), (h - c, 0), (h - c, w - c)]
        x = np.stack([img[y:y + c, x0:x0 + c] for y, x0 in pos]).astype(np.float32) / 255.0
        x = (x - IMAGENET_MEAN) / IMAGENET_STD
        return np.ascontiguousarray(x.transpose(0, 3, 1, 2), dtype=np.float32)

    def embed_rgb(self, rgb: np.ndarray) -> tuple[np.ndarray, None]:
        e = self.session.run(None, {"images": self.crops(rgb)})[0]
        e = e / np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-12)
        m = e.mean(0)
        return (m / max(float(np.linalg.norm(m)), 1e-12)).astype(np.float32), None

    def run(self, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Single-crop path for callers that already resized to 448 px (no five-crop averaging)."""
        e = self.session.run(None, {"images": np.ascontiguousarray(batch, dtype=np.float32)})[0]
        return e, np.zeros((len(e), 0), np.float32)


class TorchRuntime:
    def __init__(self, checkpoint: str | Path, threads: int = 4):
        import torch

        from ..reid.embedding import ReIDConfig, ReIDNet

        torch.set_num_threads(threads)
        ck = torch.load(checkpoint, map_location="cpu", weights_only=False)
        cfg = ReIDConfig(**{**ck["config"], "pretrained": False})
        self.model = ReIDNet(cfg).eval()
        self.model.load_state_dict(ck["state_dict"])
        self.input_size = cfg.image_size
        self.embedding_dim = self.model.embedding_dim
        self.species_labels = list(ck["species_labels"])
        self.version = ck.get("version", Path(checkpoint).stem)
        self._torch = torch

    def run(self, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        with self._torch.inference_mode():
            emb, logits = self.model(self._torch.from_numpy(np.ascontiguousarray(batch, dtype=np.float32)))
        return emb.numpy(), logits.numpy()


class MockRuntime:
    """Deterministic content-based embedding for tests (no weights needed).

    Embedding = fixed random projection of a downsampled image, so the same or
    a slightly perturbed image gives a near-identical embedding and unrelated
    images give near-orthogonal ones. Species logits come from mean colour
    (greenish-brown -> class 0) unless ``species_fn`` is given.
    """

    def __init__(self, input_size: int = 64, embedding_dim: int = 128, species_labels=None, species_fn=None, seed=0):
        from ..species.labels import SPECIES

        self.input_size = input_size
        self.embedding_dim = embedding_dim
        # species_labels=[] mimics a model without a species head (model gamma)
        self.species_labels = [] if species_labels == [] else list(species_labels or SPECIES)
        self.version = "mock"
        rng = np.random.default_rng(seed)
        self._proj = rng.normal(0, 1, (3 * 16 * 16, embedding_dim)).astype(np.float32)
        self._species_fn = species_fn

    def run(self, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        import cv2

        n = batch.shape[0]
        small = np.stack([cv2.resize(b.transpose(1, 2, 0), (16, 16), interpolation=cv2.INTER_AREA) for b in batch])
        small = small - small.mean(axis=(1, 2), keepdims=True)  # per-channel centring
        flat = small.reshape(n, -1)
        flat = flat / np.maximum(np.linalg.norm(flat, axis=1, keepdims=True), 1e-6)
        emb = flat @ self._proj
        if not self.species_labels:
            logits = np.zeros((n, 0), np.float32)
        elif self._species_fn is not None:
            logits = np.stack([self._species_fn(b) for b in batch]).astype(np.float32)
        else:
            logits = np.zeros((n, len(self.species_labels)), np.float32)
            logits[:, 0] = 5.0
        return emb.astype(np.float32), logits
