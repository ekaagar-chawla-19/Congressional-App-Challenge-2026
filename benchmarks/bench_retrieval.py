"""Gallery search latency and memory vs gallery size, plus storage per observation.

Usage: python benchmarks/bench_retrieval.py --out runs/bench/retrieval.json
"""

from __future__ import annotations

import argparse
import io
import json
import tempfile
import time
from pathlib import Path

import numpy as np

from hemlock_sentinel.database.models import ObservationRecord, ViewRecord
from hemlock_sentinel.database.repository import TreeRepository
from hemlock_sentinel.reid.retrieval import EmbeddingIndex


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dim", type=int, default=2152)
    ap.add_argument("--obs-per-tree", type=int, default=4)
    ap.add_argument("--out", default="runs/bench/retrieval.json")
    args = ap.parse_args()
    rng = np.random.default_rng(0)
    res = {"dim": args.dim, "obs_per_tree": args.obs_per_tree, "search": {}}
    for n_trees in (100, 1000, 5000):
        n = n_trees * args.obs_per_tree
        idx = EmbeddingIndex(args.dim)
        ids = [f"H-{i // args.obs_per_tree:04d}" for i in range(n)]
        t0 = time.perf_counter()
        idx.add_many(ids, rng.normal(size=(n, args.dim)).astype(np.float32))
        build = time.perf_counter() - t0
        q = rng.normal(size=(4, args.dim)).astype(np.float32)  # 3 views + aggregate, as in identify()
        idx.tree_scores(q)
        ts = []
        for _ in range(20):
            t0 = time.perf_counter()
            idx.tree_scores(q)
            ts.append(time.perf_counter() - t0)
        res["search"][f"{n_trees}_trees"] = {"observations": n, "index_ram_mb_fp32": round(idx.nbytes() / 1e6, 2),
                                             "build_ms": round(1000 * build, 1),
                                             "search_ms_median": round(1000 * float(np.median(ts)), 2)}

    # DB + blob storage per observation (synthetic sizes for embeddings/local features)
    with tempfile.TemporaryDirectory() as d:
        repo = TreeRepository(Path(d) / "t.sqlite")
        tid = repo.create_tree("tsuga_canadensis", "H")
        for k in range(50):
            e = rng.normal(size=args.dim)
            repo.add_observation(ObservationRecord("", tid, float(k), "existing", "tsuga_canadensis", 0.9, 0.9, e,
                                                   views=[ViewRecord(i, "trunk_north", f"key{k}_{i}", e)
                                                          for i in range(3)]))
        repo.close()
        db_bytes = sum(p.stat().st_size for p in Path(d).glob("t.sqlite*"))
    buf = io.BytesIO()
    np.savez_compressed(buf, kp=rng.uniform(0, 640, (500, 2)).astype(np.float32),
                        desc=rng.integers(0, 80, (500, 128)).astype(np.uint8))
    res["storage_per_observation"] = {
        "db_kb_per_3view_observation": round(db_bytes / 50 / 1024, 1),
        "embedding_kb_fp16_each": round(args.dim * 2 / 1024, 1),
        "local_features_kb_per_view_npz": round(len(buf.getvalue()) / 1024, 1),
        "note": "plus original JPEGs (stored once, content-addressed); typically 1-4 MB per phone photo",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
