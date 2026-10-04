"""Regression: training-from-cache -> export -> ONNX parity, on a tiny fake cache.

Covers two bugs found during development:
* train_tail crashed when a training tree had no cached samples (margin vector
  length != number of identities);
* export mapped ``stage5.<i>`` keys to the wrong backbone block (nn.Sequential
  slicing keeps the original indices).
Needs the ImageNet weights for efficientnetv2_rw_m (downloaded by timm), so
it is marked slow.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from hemlock_sentinel.evaluation.splits import ImageRecord, write_manifest
from hemlock_sentinel.species.labels import SPECIES

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.slow
def test_train_tail_then_export_roundtrip(tmp_path, bark):
    import cv2

    data, cache = tmp_path / "data", tmp_path / "cache"
    data.mkdir()
    cache.mkdir()
    recs = []
    for t in range(4):
        for v in range(4):
            p = tmp_path / f"img_{t}_{v}.jpg"
            cv2.imwrite(str(p), bark(t * 10 + v, 200, 160))
            recs.append(ImageRecord(str(p), f"PRU-{t}", "tsuga_canadensis", "20170101", f"PRU-{t}@x", "Nexus 5", 100, v))
    write_manifest(recs, data / "manifest.csv")
    # PRU-2 is a training tree with NO cached augmentations (regression case)
    (data / "splits.json").write_text(json.dumps({"train": ["PRU-0", "PRU-1", "PRU-2"], "val": ["PRU-3"],
                                                  "test": [], "held_out_species": []}))
    rows = [i for i, r in enumerate(recs) if r.tree_id in ("PRU-0", "PRU-1")]
    np.save(cache / "eval_trunk.npy", np.random.default_rng(0).normal(size=(16, 192, 4, 4)).astype(np.float16))
    np.save(cache / "train_aug_trunk.npy", np.random.default_rng(1).normal(size=(len(rows), 192, 4, 4)).astype(np.float16))
    np.save(cache / "train_aug_rows.npy", np.array(rows))
    out = tmp_path / "run"
    subprocess.run([sys.executable, str(ROOT / "training/reid/train_tail.py"), "--cache", str(cache), "--data", str(data),
                    "--out", str(out), "--epochs", "1", "--p", "2", "--k", "2", "--threads", "1"], check=True)
    assert np.load(out / "embeddings.npy").shape == (16, 2152)

    np.savez(tmp_path / "sp.npz", W=np.random.default_rng(2).normal(size=(len(SPECIES), 2152)).astype(np.float32),
             b=np.zeros(len(SPECIES), np.float32), labels=np.array(SPECIES), threshold=np.float32(0.5))
    subprocess.run([sys.executable, str(ROOT / "scripts/export_model.py"), "--tail", str(out / "tail.pt"),
                    "--species", str(tmp_path / "sp.npz"), "--out", str(tmp_path / "exp/hemlock"),
                    "--image-size", "128", "--check-images", str(recs[0].path)], check=True)
    parity = json.loads((tmp_path / "exp/parity.json").read_text())
    assert parity["min_cosine_torch_vs_onnx"] > 0.9999

    # the fine-tuned tail weights really ended up in the exported model
    import torch

    tail = torch.load(out / "tail.pt", weights_only=False)["tail"]
    full = torch.load(tmp_path / "exp/hemlock.pt", weights_only=False)["state_dict"]
    k = next(k for k in tail if k.startswith("stage5.") and k.endswith("conv_pw.weight"))
    assert torch.equal(tail[k], full["backbone.model.blocks." + k[len("stage5."):]])
    assert torch.equal(tail["head.bn.running_mean"], full["bn.running_mean"])
