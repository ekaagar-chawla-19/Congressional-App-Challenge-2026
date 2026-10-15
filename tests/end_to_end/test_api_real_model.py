"""Mobile API with the shipped production model (models/production) on held-out BarkNet trees.

Skipped unless the BarkNet manifest exists (runs/data, see README "Reproduce").
Only TEST-split hemlocks (never trained on) and red spruce (never seen at all).
"""

import json
from pathlib import Path

import pytest

from hemlock_sentinel.api.server import DEFAULT_CALIBRATION, DEFAULT_MODEL

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "runs/data"

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(not (DEFAULT_MODEL.exists() and (DATA / "manifest.csv").exists()),
                                 reason="production model / BarkNet manifest not available")]


def _trees():
    from hemlock_sentinel.evaluation.splits import read_manifest

    test = set(json.loads((DATA / "splits.json").read_text())["test"])
    by = {}
    for r in read_manifest(DATA / "manifest.csv"):
        if (r.tree_id in test and r.species == "tsuga_canadensis") or r.species == "picea_rubens":
            by.setdefault((r.species, r.tree_id), []).append(r.path)
    return {k: sorted(v) for k, v in by.items()}


def test_production_model_through_api(tmp_path):
    from fastapi.testclient import TestClient

    from hemlock_sentinel.api.server import create_api
    from hemlock_sentinel.app.server import build_pipeline

    pipe, demo = build_pipeline(str(tmp_path / "db.sqlite"), str(tmp_path / "blobs"), str(DEFAULT_MODEL),
                                str(DEFAULT_CALIBRATION))
    c = TestClient(create_api(pipe, demo))
    assert c.get("/api/v1/model").json()["version"].startswith("hemlock-dino_plus_recapture")

    def send(paths):
        files = [("images", (Path(p).name, Path(p).read_bytes(), "image/jpeg")) for p in paths]
        return c.post("/api/v1/identify", files=files).json()

    trees = _trees()
    hem = sorted(k for k in trees if k[0] == "tsuga_canadensis")
    ids = {}
    for k in hem[:5]:
        r = send(trees[k][:3])
        assert r["status"] == "new" and r["species"]["label"] == "tsuga_canadensis", r
        ids[k] = r["tree_id"]
    top1 = 0
    for k in hem[:5]:  # revisit with different photos
        r = send(trees[k][3:6])
        assert not (r["status"] == "existing" and r["tree_id"] != ids[k]), r
        top1 += r["candidates"][0]["tree_id"] == ids[k]
    assert top1 >= 4
    r = send(trees[hem[6]][:3])  # never enrolled
    assert r["status"] in ("new", "uncertain"), r
    spruce = next(k for k in trees if k[0] == "picea_rubens")
    r = send(trees[spruce][:3])
    assert r["status"] in ("rejected_species", "unsupported_species") and r["tree_id"] is None, r
