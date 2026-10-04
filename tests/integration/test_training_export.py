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


@pytest.mark.slow
def test_dinov2_last_block_tail_export_mapping(tmp_path, bark):
    """Regression: ViT tail keys (tail.blocks.<i>, tail.norm) must land in the right backbone blocks,
    and the ONNX graph must not depend on traced token counts."""
    import importlib.util

    import cv2
    import torch

    spec = importlib.util.spec_from_file_location("train_tail", ROOT / "training/reid/train_tail.py")
    tt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tt)
    name = "vit_small_patch14_dinov2.lvd142m"
    tail = tt.Tail(name, pretrained=False, img_size=56, split="last_block")
    torch.manual_seed(0)
    for p in tail.parameters():
        p.data.normal_(0, 0.02)
    torch.save({"tail": tail.state_dict(), "backbone": name, "split": "last_block"}, tmp_path / "tail.pt")
    np.savez(tmp_path / "sp.npz", W=np.random.default_rng(2).normal(size=(len(SPECIES), 384)).astype(np.float32),
             b=np.zeros(len(SPECIES), np.float32), labels=np.array(SPECIES), threshold=np.float32(0.5))
    img = tmp_path / "x.jpg"
    cv2.imwrite(str(img), bark(1, 120, 100))
    subprocess.run([sys.executable, str(ROOT / "scripts/export_model.py"), "--tail", str(tmp_path / "tail.pt"),
                    "--species", str(tmp_path / "sp.npz"), "--out", str(tmp_path / "exp/hemlock"),
                    "--image-size", "56", "--check-images", str(img)], check=True)
    full = torch.load(tmp_path / "exp/hemlock.pt", weights_only=False)["state_dict"]
    sd = tail.state_dict()
    assert torch.equal(sd["tail.blocks.11.mlp.fc1.weight"], full["backbone.model.blocks.11.mlp.fc1.weight"])
    assert torch.equal(sd["tail.norm.weight"], full["backbone.model.norm.weight"])
    assert torch.equal(sd["head.pool.p"], full["pool.p"])
    assert json.loads((tmp_path / "exp/parity.json").read_text())["min_cosine_torch_vs_onnx"] > 0.9999
