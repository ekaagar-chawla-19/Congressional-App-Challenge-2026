"""INT8 post-training quantisation of the exported ONNX model (only after FP32 is validated).

Static QDQ quantisation (per-channel weights, activations calibrated on TRAIN
images — never val/test). Accuracy is then measured through the deployed path
(scripts/embed_with_runtime.py + evaluate_reid.py) and compared to FP32.

Usage: python scripts/quantize_model.py --model runs/export/hemlock.onnx --out runs/export/hemlock_int8.onnx
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

import numpy as np
from onnxruntime.quantization import CalibrationDataReader, CalibrationMethod, QuantFormat, QuantType, quantize_static
from onnxruntime.quantization.shape_inference import quant_pre_process

from hemlock_sentinel.evaluation.splits import read_manifest
from hemlock_sentinel.preprocessing import decode_image, to_network_input


class TrainImages(CalibrationDataReader):
    def __init__(self, paths, size):
        self.it = iter(paths)
        self.size = size

    def get_next(self):
        p = next(self.it, None)
        if p is None:
            return None
        return {"images": to_network_input(decode_image(Path(p).read_bytes()), self.size)[None]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default="runs/data")
    ap.add_argument("--n-calib", type=int, default=96)
    ap.add_argument("--calib-method", default="MinMax", choices=["MinMax", "Percentile", "Entropy"])
    ap.add_argument("--op-types", nargs="*", default=None,
                    help="quantise only these op types (e.g. Conv) — keeps GeM/BN/head in FP32")
    args = ap.parse_args()
    meta = json.loads(Path(args.model).with_suffix(".json").read_text())
    recs = read_manifest(Path(args.data) / "manifest.csv")
    sp = json.loads((Path(args.data) / "splits.json").read_text())
    train = [r.path for r in recs if r.tree_id in set(sp["train"])]
    random.Random(0).shuffle(train)
    pre = Path(args.out).with_suffix(".pre.onnx")
    quant_pre_process(args.model, str(pre))
    quantize_static(str(pre), args.out, TrainImages(train[: args.n_calib], meta["image_size"]),
                    quant_format=QuantFormat.QDQ, per_channel=True,
                    activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8,
                    op_types_to_quantize=args.op_types,
                    calibrate_method=getattr(CalibrationMethod, args.calib_method))
    pre.unlink()
    shutil.copy(Path(args.model).with_suffix(".json"), Path(args.out).with_suffix(".json"))
    print({"fp32_mb": round(Path(args.model).stat().st_size / 1e6, 1),
           "int8_mb": round(Path(args.out).stat().st_size / 1e6, 1), "calibration_images": args.n_calib})


if __name__ == "__main__":
    main()
