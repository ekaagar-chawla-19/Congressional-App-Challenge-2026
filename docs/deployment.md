# Deployment

Training happens on a workstation or cloud machine. Inference runs on the
handheld: a Raspberry Pi 5 with a camera, or a phone that talks to the Pi or to a
laptop. This page covers export, Pi setup, and measured cost.

Read "Measured cost" carefully. All numbers were measured on this project's
development machine (x86-64, 4 vCPU cloud container, no GPU). **No number here
was measured on a Raspberry Pi**, because none was available. The scaling notes
explain what to expect and how to measure it on the device
(`benchmarks/bench_inference.py`).

## 1. Export

```bash
python scripts/export_model.py --tail runs/reid/subcenter/tail.pt \
    --species runs/species/subcenter/species_head.npz --out runs/export/hemlock \
    --check-images <a few real jpgs>
python scripts/calibrate.py ... --out runs/export/calibration.json
```

Outputs:

| File | Purpose |
|---|---|
| `hemlock.onnx` | Opset 17, input `images` (N,3,322,322) float32; outputs `embedding` (N,384), `species_logits` (N,C) |
| `hemlock.json` | Sidecar: image size, embedding dim, species labels, version, preprocessing spec |
| `hemlock.pt` | Same weights for the Torch runtime (development) |
| `parity.json` | Torch vs ONNX Runtime on real images. Export fails unless min cosine > 0.9999 |
| `calibration.json` | Every decision threshold plus its provenance (fitted on validation trees) |

Preprocessing is part of the contract, not the graph:

* decode JPEG with EXIF orientation
* resize so the short side is 322 (INTER_AREA)
* centre-crop 322×322
* divide by 255 and apply ImageNet mean/std

It lives in `hemlock_sentinel/preprocessing.py` and is shared by training-time
evaluation and inference.

## 2. Raspberry Pi 5 setup

```bash
sudo apt install -y python3-venv python3-picamera2 gpsd python3-gps   # camera + GPS
python3 -m venv --system-site-packages ~/hs && . ~/hs/bin/activate       # system-site for picamera2
pip install -e ".[onnx,app]"            # no torch needed on the device
python -m hemlock_sentinel.acquisition.devices   # hardware smoke test (camera / RealSense / GPS)
hemlock-app --model hemlock.onnx --calibration calibration.json \
    --ssl-certfile cert.pem --ssl-keyfile key.pem
```

* **Runtime.** ONNX Runtime CPU (aarch64 wheels on PyPI). Torch is not required on the device. Use 4 intra-op threads on the Pi 5's 4 Cortex-A76 cores.
* **Optional accelerator.** The structure maps onto ONNX-consuming NPUs (e.g. Hailo-8L on the Pi AI Kit) after INT8 compilation with their toolchain. This has **not** been done or measured. Validate retrieval accuracy after compilation with `scripts/evaluate_reid.py` before trusting it.
* **HTTPS.** Phones grant camera access only on HTTPS or localhost. Use a self-signed certificate for the Pi's hotspot address, or run the browser on the Pi itself (kiosk) against `http://localhost:8000`.
* **Depth (optional).** RealSense D4xx over USB (`pip install pyrealsense2` where wheels exist, else build librealsense). The adapter is in `acquisition/devices.py` and is **untested on hardware**. Prefer the D435f/D455f "f" variants (IR-pass filter) in sunlight.
* **Storage.** Use an SD card or USB SSD. The DB uses WAL mode, and images are content-addressed under `runs/app/blobs`.

## 3. Measured cost (development machine; see docs/experiments.md E-efficiency)

Measured on x86-64, 4 vCPU, no GPU, ONNX Runtime 1.30, each runtime in a fresh process:

| Production model: DINOv2-S/14 FP32 ONNX | 4 threads | 1 thread |
|---|---|---|
| Model file | 87 MB | 87 MB |
| Model load | 0.30 s | 0.26 s |
| JPEG decode, 12 MP phone photo (DCT-scaled to 1008×756) | 45 ms | – |
| Preprocess (resize + crop + normalise) | 4 ms | 5 ms |
| Inference per view | 75 ms | 234 ms |
| Per view total (BarkNet 2220×3830 photo) | 117 ms | 278 ms |
| 3 views / 5 views | 0.35 s / 0.58 s | 0.83 s / 1.39 s |
| Peak RSS (whole process) | 273 MB | 272 MB |
| Gallery search, 1,000 trees × 4 observations | 0.43 ms | – |
| Index RAM, 1,000 trees | 6 MB | – |
| SQLite per 3-view observation (excl. JPEGs) | ~5 KB | – |

**Expectations for a Raspberry Pi 5.** These are not measured. The Pi 5's 4×Cortex-A76 is typically several times slower than one modern x86 core for FP32 ViT inference, so expect on the order of 0.5–1.5 s per view with 4 threads. Measure on the device with:

```bash
python benchmarks/bench_inference.py --runtime onnx --model hemlock.onnx --threads 4 \
    --images <a few phone JPEGs> --out pi5.json
```

and record the result in docs/experiments.md. Each view is embedded right after capture while the user walks to the next position, so the user mostly waits only for retrieval and the decision (milliseconds).

## 4. What dominates, and what to do on a Pi

* **Image inference dominates.** Everything else (quality checks, retrieval, decision, DB write) is milliseconds. The Pi 5 is several times slower than a modern x86 core for this workload, so expect seconds per view. The UI hides most of it: each view is embedded right after capture while the user walks to the next position, so "Identify" only runs retrieval and the decision.
* **Levers, in order of safety:**
  1. Lower input resolution (e.g. 256): cost scales roughly with pixel count. Re-validate accuracy, because bark texture needs resolution.
  2. INT8 quantisation: only after the FP32 model is validated, and only if retrieval metrics on the validation split stay within noise. Post-training static INT8 of the earlier EfficientNetV2-M model lost 11–20 % mAP (E-quantisation), so FP32 ships. INT8 for DINOv2-S has not been evaluated; try quantisation-aware training before shipping it.
  3. A smaller backbone: only via a new controlled comparison. The current results do not support swapping casually.
* **Memory.** One model instance is loaded once per process and shared by all requests. JPEGs are decoded once, directly at reduced scale (DCT scaling), and the decoded array is dropped after embedding. Only embeddings and the original JPEG bytes are kept until commit. The in-RAM index is 1.5 KB per stored observation (384-d float32).
