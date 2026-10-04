"""Embed images through the DEPLOYED path (ModelRuntime + app preprocessing).

Used to verify that metrics computed from the training cache reproduce with
the exported ONNX model and the app's decode/resize code. Rows not embedded
are NaN; evaluate with scripts/evaluate_reid.py --hemlock-only.

Usage: python scripts/embed_with_runtime.py --model runs/export/hemlock.onnx --out runs/reid/onnx/embeddings.npy
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.pipeline.runtime import OnnxRuntime
from hemlock_sentinel.preprocessing import decode_image, to_network_input


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args()
    recs = read_manifest(Path(args.data) / "manifest.csv")
    sp = json.loads((Path(args.data) / "splits.json").read_text())
    ids = set(sp["val"]) | set(sp["test"])
    rows = [i for i, r in enumerate(recs) if r.tree_id in ids and r.species == "tsuga_canadensis"]
    rt = OnnxRuntime(args.model, threads=args.threads)
    emb = np.full((len(recs), rt.embedding_dim), np.nan, np.float32)
    t0 = time.time()
    for i in rows:
        x = to_network_input(decode_image(Path(recs[i].path).read_bytes()), rt.input_size)[None]
        emb[i] = rt.run(x)[0][0]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    np.save(args.out, emb)
    print(f"{len(rows)} images in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
