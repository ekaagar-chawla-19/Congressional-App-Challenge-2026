"""Server-side reference for the on-device (JavaScript) port: client/test/parity.mjs.

Uses the production model on held-out BarkNet test hemlocks (never trained on):
enrols the first 3 photos of N trees through the real server pipeline, then records,
for revisit captures (3 other photos of each enrolled tree, plus captures of trees
that were never enrolled), the server's per-view embeddings, quality metrics and its
final decision. The JS engine must reproduce them.

Usage: python scripts/ondevice_parity_fixture.py --out client/test/fixture.json [--trees 8]
"""

from __future__ import annotations

import argparse
import base64
import json
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from hemlock_sentinel.acquisition.interfaces import Frame
from hemlock_sentinel.api.server import DEFAULT_CALIBRATION, DEFAULT_MODEL
from hemlock_sentinel.app.server import build_pipeline
from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.preprocessing import decode_image

KEYS = ["trunk_north", "trunk_right", "trunk_right2"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--trees", type=int, default=8)
    ap.add_argument("--new-trees", type=int, default=3)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    test = set(json.loads((Path(a.data) / "splits.json").read_text())["test"])
    by: dict[str, list[str]] = {}
    for r in read_manifest(Path(a.data) / "manifest.csv"):
        if r.tree_id in test and r.species == "tsuga_canadensis":
            by.setdefault(r.tree_id, []).append(r.path)
    trees = [t for t in sorted(by) if len(by[t]) >= 6][: a.trees + a.new_trees]
    enrolled, unseen = trees[: a.trees], trees[a.trees:]

    d = tempfile.mkdtemp()
    pipe, _ = build_pipeline(f"{d}/db.sqlite", f"{d}/blobs", str(DEFAULT_MODEL), str(DEFAULT_CALIBRATION))
    pipe.cfg.blur_faces = False  # the JS port does not blur faces (the server does on sync)

    def views(paths):
        out = []
        for i, p in enumerate(paths):
            data = Path(p).read_bytes()
            out.append(pipe.process_view(Frame(decode_image(data), time.time(), encoded=data), i, out,
                                         view_key=KEYS[i]))
        return out

    ids = {}
    for t in enrolled:
        r = pipe.identify(views(sorted(by[t])[:3]))
        ids[t] = r.tree_id
    tids, oids, emb = pipe.repo.gallery("tsuga_canadensis")
    gallery = {"model_version": pipe.runtime.version, "embedding_dim": int(emb.shape[1]), "species": "tsuga_canadensis",
               "tree_ids": sorted(set(tids)),
               "observations": [{"tree_id": t, "observation_id": o, "embedding_b64": base64.b64encode(
                   (np.asarray(e, np.float32) / np.linalg.norm(e)).astype("<f4").tobytes()).decode()}
                   for t, o, e in zip(tids, oids, emb)]}

    queries = []
    for t in enrolled + unseen:
        paths = sorted(by[t])[3:6] if t in ids else sorted(by[t])[:3]
        vs = views(paths)
        r = pipe.identify(vs, commit=False)
        queries.append({
            "tree": t, "truth": ids.get(t), "paths": [str(Path(p).resolve()) for p in paths],
            "views": [{"accepted": v.accepted, "weight": v.quality.weight,
                       "laplacian_var": v.quality.metrics["laplacian_var"],
                       "embedding": None if v.embedding is None else [round(float(x), 6) for x in v.embedding]}
                      for v in vs],
            "server": {"status": r.status, "tree_id": r.tree_id,
                       "probability": None if r.decision is None else r.decision.probability,
                       "top": None if not (r.decision and r.decision.candidates) else r.decision.candidates[0]["tree_id"],
                       "species_confidence": r.species.confidence if r.species else None}})
    meta = json.loads(Path(DEFAULT_MODEL).with_suffix(".json").read_text())
    Path(a.out).write_text(json.dumps({"model": str(Path(DEFAULT_MODEL).resolve()), "meta": meta,
                                       "calibration": asdict(pipe.cal), "gallery": gallery, "queries": queries}))
    print(f"{len(queries)} queries ({len(enrolled)} enrolled trees, {len(unseen)} never enrolled) -> {a.out}")


if __name__ == "__main__":
    main()
