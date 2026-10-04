"""Latency / memory benchmark of one runtime, in a fresh process (clean peak-RSS).

Measures: model load time, JPEG decode, preprocessing, per-view inference,
3- and 5-view totals (sequential, as captured), peak RSS.

Usage:
    python benchmarks/bench_inference.py --runtime onnx --model runs/export/hemlock.onnx --threads 4 \
        --images img1.jpg img2.jpg ... --out runs/bench/onnx_fp32.json
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import time
from pathlib import Path

import numpy as np


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0  # Linux: KiB


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", choices=["onnx", "torch"], required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--images", nargs="+", required=True)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--full-decode", action="store_true", help="decode JPEGs at full resolution")
    args = ap.parse_args()

    from hemlock_sentinel.preprocessing import decode_image, to_network_input

    rss0 = peak_rss_mb()
    t0 = time.perf_counter()
    if args.runtime == "onnx":
        from hemlock_sentinel.pipeline.runtime import OnnxRuntime

        rt = OnnxRuntime(args.model, threads=args.threads)
    else:
        from hemlock_sentinel.pipeline.runtime import TorchRuntime

        rt = TorchRuntime(args.model, threads=args.threads)
    load_s = time.perf_counter() - t0
    rss_loaded = peak_rss_mb()

    blobs = [Path(p).read_bytes() for p in args.images]
    dec, pre, inf = [], [], []
    rt.run(to_network_input(decode_image(blobs[0]), rt.input_size)[None])  # warm-up
    for _ in range(args.repeats):
        for b in blobs:
            t = time.perf_counter()
            rgb = decode_image(b, None) if args.full_decode else decode_image(b)
            t1 = time.perf_counter()
            x = to_network_input(rgb, rt.input_size)[None]
            t2 = time.perf_counter()
            rt.run(x)
            t3 = time.perf_counter()
            dec.append(t1 - t)
            pre.append(t2 - t1)
            inf.append(t3 - t2)
    per_view = np.median(dec) + np.median(pre) + np.median(inf)
    res = {
        "runtime": args.runtime, "model": args.model, "threads": args.threads,
        "machine": platform.machine(), "processor": platform.processor() or platform.platform(),
        "model_file_mb": round(Path(args.model).stat().st_size / 1e6, 1),
        "load_seconds": round(load_s, 3),
        "decode_ms_median": round(1000 * float(np.median(dec)), 1),
        "preprocess_ms_median": round(1000 * float(np.median(pre)), 1),
        "inference_ms_median": round(1000 * float(np.median(inf)), 1),
        "inference_ms_p90": round(1000 * float(np.percentile(inf, 90)), 1),
        "per_view_total_ms": round(1000 * per_view, 1),
        "three_views_total_ms": round(3000 * per_view, 1),
        "five_views_total_ms": round(5000 * per_view, 1),
        "rss_before_load_mb": round(rss0, 1), "rss_after_load_mb": round(rss_loaded, 1),
        "peak_rss_mb": round(peak_rss_mb(), 1),
        "source_image_px": list(decode_image(blobs[0], None).shape[:2]),
        "decoded_px": list((decode_image(blobs[0], None) if args.full_decode else decode_image(blobs[0])).shape[:2]),
        "n_images": len(blobs), "full_decode": args.full_decode,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
