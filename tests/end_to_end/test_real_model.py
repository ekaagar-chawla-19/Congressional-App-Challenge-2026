"""End-to-end with the REAL exported model and calibration on held-out BarkNet trees.

Skipped unless the trained artefacts and the data manifest exist
(runs/export/hemlock.onnx, runs/export/calibration.json, runs/data/*), i.e. after
`bash scripts/finalize.sh ...`. Uses only TEST-split trees (never trained on)
and red spruce (never seen in training or tuning).
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "runs/export/hemlock.onnx"
CAL = ROOT / "runs/export/calibration.json"
DATA = ROOT / "runs/data"

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(not (MODEL.exists() and CAL.exists() and (DATA / "manifest.csv").exists()),
                                 reason="trained model / data not available")]


def _client(tmp_path):
    from fastapi.testclient import TestClient

    from hemlock_sentinel.app.server import build_pipeline, create_app

    pipe, demo = build_pipeline(str(tmp_path / "db.sqlite"), str(tmp_path / "blobs"), str(MODEL), str(CAL))
    assert not demo
    return TestClient(create_app(pipe)), pipe


def _trees():
    from hemlock_sentinel.evaluation.splits import read_manifest

    recs = read_manifest(DATA / "manifest.csv")
    sp = json.loads((DATA / "splits.json").read_text())
    by = {}
    for r in recs:
        if (r.tree_id in set(sp["test"]) and r.species == "tsuga_canadensis") or r.species == "picea_rubens":
            by.setdefault((r.species, r.tree_id), []).append(r.path)
    return by


def _capture(c, paths):
    sid = c.post("/api/session").json()["session_id"]
    for p in paths:
        c.post(f"/api/session/{sid}/view", files={"image": ("v.jpg", Path(p).read_bytes())})
    return sid, c.post(f"/api/session/{sid}/identify", data={"force_commit": "true"}).json()


def test_real_model_enrol_recognise_reject(tmp_path):
    c, pipe = _client(tmp_path)
    trees = _trees()
    hem = sorted(k for k in trees if k[0] == "tsuga_canadensis")
    spruce = sorted(k for k in trees if k[0] == "picea_rubens")

    # enrol 5 test hemlocks (first 3 images each)
    ids = {}
    for k in hem[:5]:
        _, r = _capture(c, sorted(trees[k])[:3])
        assert r["species"]["label"] == "tsuga_canadensis", r
        assert r["status"] == "new", r
        ids[k] = r["tree_id"]
    assert sorted(ids.values()) == ["H-001", "H-002", "H-003", "H-004", "H-005"]

    # revisit with three DIFFERENT images of each tree: never a wrong existing ID,
    # and the true tree is the top candidate for most of them
    top1 = 0
    for k in hem[:5]:
        _, r = _capture(c, sorted(trees[k])[3:6])
        assert not (r["status"] == "existing" and r["tree_id"] != ids[k]), r
        top1 += r["candidates"][0]["tree_id"] == ids[k]
    assert top1 >= 4

    # a hemlock never enrolled must not be matched to an existing tree
    _, r = _capture(c, sorted(trees[hem[6]])[:3])
    assert r["status"] in ("new", "uncertain"), r

    # red spruce (never seen in training or tuning) must not receive a hemlock ID
    _, r = _capture(c, sorted(trees[spruce[0]])[:3])
    assert r["status"] in ("rejected_species", "unsupported_species"), r
    assert r["tree_id"] is None
