# Hemlock Sentinel

**Status: prototype** (branch `prototypes/hemlock-sentinel`).

Hemlock Sentinel is a handheld system for identifying and monitoring individual
**Eastern hemlocks** (*Tsuga canadensis*) in North Georgia. A plain classifier
can say *"this is an Eastern hemlock."* Hemlock Sentinel answers a harder
question: *"this is the same physical tree we recorded as H-017 last October."*
It then stores the new observation in that tree's history for later change
detection.

```
Species:     Eastern hemlock — 97%
Individual:  H-017 — 94%
```

The user takes 3–5 guided photos (trunk from the north side, two quarter-turns
around the tree, then optionally branching and canopy). Depth is used when
available. The system:

1. checks image quality and blurs any faces;
2. runs one shared **EfficientNetV2-M → GeM → BatchNorm** network per view, which gives a species prediction and a 2152-d identity embedding;
3. refuses to assign an ID unless the species is supported and above a **validated** confidence threshold;
4. averages the views into one tree embedding and runs a cosine search over every stored observation;
5. scores the top candidates with global similarity, view agreement and, optionally, local bark keypoints and trunk structure from depth, using a **calibrated** model fitted on validation data;
6. decides **existing tree**, **new tree** (gets the next persistent ID, e.g. `H-158`), or **uncertain** (contradicting views: take another view, or the user decides);
7. persists the observation (SQLite + content-addressed files) so the tree's history accumulates.

How it works: [`docs/architecture.md`](docs/architecture.md).
Why each part exists: [`docs/research/literature_review.md`](docs/research/literature_review.md).
What was measured: [`docs/experiments.md`](docs/experiments.md).
Running on a Raspberry Pi: [`docs/deployment.md`](docs/deployment.md).

## What the evidence does and does not support

* All hemlock numbers come from **BarkNet 1.0** (MIT): 45 hemlocks, about 22 bark photos each, all from **one session per tree**. They measure "same tree, new bark region, same day" on trees never seen in training. The test set is 14 hemlocks, so confidence intervals are wide.
* **Cross-season re-identification has not been tested.** No openly licensed dataset with repeat visits of individual hemlocks exists that we could find. The app is built to collect one.
* Depth matching is implemented and tested only on **simulated** trunks. It stays off until it is calibrated on real field depth.

## Repository layout

```
src/hemlock_sentinel/
  acquisition/   hardware interfaces + mocks, device adapters, guided protocol, quality checks, face blur
  species/       species labels, gated species decision
  reid/          backbone, GeM, embedding net, losses, multi-view aggregation, retrieval,
                 local matching (RootSIFT, trunk profile), calibration, fusion/decision
  database/      SQLite schema, repository (persistent IDs), in-memory index
  pipeline/      end-to-end inference, model runtimes (ONNX / Torch / Mock)
  evaluation/    leakage-safe splits, metrics, open-set protocols
  app/           FastAPI server + single-page guided-capture UI
training/        reid/ (trunk caching, tail fine-tuning, aggregator ablation), species/
scripts/         data prep, evaluation, calibration, export, ablations
benchmarks/      inference and retrieval benchmarks
tests/           unit / numerical / integration / end_to_end
docs/            architecture, deployment, experiments, research/
```

## Setup

```bash
python -m pip install -e ".[torch,onnx,app,dev]"      # Python >= 3.10
pytest -q -m "not slow"                                 # fast suite (no weights needed)
pytest -q                                               # + training/export regression (downloads ImageNet weights)
```

## Try the app (demo mode, no trained model)

```bash
hemlock-app --port 8000        # open http://localhost:8000 — banner says DEMO (mock model)
```

Phones only give web pages camera access over HTTPS (or localhost). See
`docs/deployment.md` for `--ssl-certfile/--ssl-keyfile`. Without HTTPS, the
"Upload" button still uses the phone camera through the file picker.

## Reproduce the results

```bash
# 1. data: BarkNet 1.0 (Zenodo 11508014, MIT), species used: PRU PIB PIR PID HEG ERR ERB PEG (+ THO, EPR held out)
python scripts/prepare_barknet.py --root /data/barknet --out runs/data            # manifest + tree-disjoint splits
python scripts/calibrate_quality.py                                               # quality thresholds

# 2. features + training (CPU budget: frozen trunk is cached once, tail fine-tuned)
python training/reid/cache_trunk.py --out runs/cache --size 320 --train-augs 4
python training/reid/train_tail.py --loss subcenter_arcface --epochs 6 --out runs/reid/subcenter
python training/species/train_head.py --emb runs/reid/subcenter/embeddings.npy --out runs/species/subcenter

# 3. evaluation, ablations, calibration
python scripts/evaluate_reid.py --emb runs/reid/subcenter/embeddings.npy --name subcenter --out runs/results/subcenter.json
python scripts/zero_shot_backbones.py
bash   scripts/run_ablations.sh
python training/reid/train_aggregator.py --emb runs/reid/subcenter/embeddings.npy --out runs/results/aggregators.json
python scripts/evaluate_local.py --emb runs/reid/subcenter/embeddings.npy --out runs/results/local.json
python scripts/evaluate_depth.py
python scripts/calibrate.py --emb runs/reid/subcenter/embeddings.npy \
       --species runs/species/subcenter/species_results.json \
       --out runs/export/calibration.json --report runs/results/decision.json

# 4. export + benchmarks
python scripts/export_model.py --tail runs/reid/subcenter/tail.pt \
       --species runs/species/subcenter/species_head.npz --out runs/export/hemlock
python benchmarks/bench_inference.py --runtime onnx --model runs/export/hemlock.onnx --images <jpgs> --out runs/bench/onnx.json
python benchmarks/bench_retrieval.py

# 5. run with the trained model
hemlock-app --model runs/export/hemlock.onnx --calibration runs/export/calibration.json
```

With a GPU, skip the trunk cache and fine-tune end to end. The model, loss,
splits and evaluation code are the same.

## Collecting the team's own dataset

Every capture made with the app is stored with:

* its original JPEGs
* view type (north trunk / +90° / +180° / branching / canopy) and compass heading
* GPS and timestamp
* the quality metrics
* the assigned tree ID

Uncertain observations are stored unassigned and can be resolved later. Repeat
visits to tagged trees across seasons produce exactly the cross-session data
needed to (a) test seasonal re-identification and (b) retrain on hemlocks with
canopy and branching views.
