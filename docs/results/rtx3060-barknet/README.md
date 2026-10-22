# BarkNet re-identification runs on an RTX 3060

This directory contains the logs, evaluation JSON, and exact YAML configs for
three 20-epoch runs on the full BarkNet 1.0 dataset. The run code was the
`ekaagar-chawla-19/CAC` repository, branch
[`results/full-barknet-rtx3060`](https://github.com/ekaagar-chawla-19/CAC/tree/results/full-barknet-rtx3060).
This report and its artifacts are mirrored here so they are alongside the
current Congressional App Challenge project.

## Setup and method

- Hardware: NVIDIA RTX 3060 12 GB, Windows 11, 32 GB system RAM.
- Data: full 23-species BarkNet 1.0 download (Zenodo record 11508014), 23,528
  images. The split uses 890 train trees / 21,218 images; validation is the
  held-out EPO species; test is 45 PRU hemlocks, with 35 gallery trees and 10
  held out as unseen.
- Tests: `pytest -q` passed, 14 tests.
- Baseline: pretrained DINOv2 ViT-S/14, no fine-tuning; evaluated with four
  pooling modes.
- Training: Sub-center ArcFace, dynamic margins, last four transformer blocks
  fine-tuned, 20 epochs, batch 64, fp16 AMP. Best checkpoint is selected by
  validation mAP. The three trained runs change one factor at a time relative
  to ViT-S at 224 px: input resolution or backbone size.
- Checkpoints are attached to the GitHub release
  [`barknet-rtx3060`](https://github.com/ekaagar-chawla-19/Congressional-App-Challenge-2026/releases/tag/barknet-rtx3060).

## Hemlock test results

There are 35 known hemlocks in the gallery (chance top-1 = 2.9%) and 10
unseen hemlocks. Higher top-k means better identification; higher new-tree
AUROC means better separation of unseen from known trees.

| Run | Best epoch | mAP | Top-1 @1 / 3 / 5 photos | Top-5 @1 / 3 / 5 photos | New-tree AUROC @1 / 3 / 5 |
|---|---:|---:|---|---|---|
| ViT-S zero-shot, CLS+mean | — | 0.231 | 39.2 / 40.0 / 34.1% | 67.6 / 74.3 / 76.5% | 0.52 / 0.45 / 0.45 |
| ViT-S, 224 px | 14 | 0.431 | 59.0 / 70.9 / 75.9% | 85.6 / 90.3 / 91.8% | 0.63 / 0.65 / 0.63 |
| ViT-B, 224 px | 8 | 0.448 | 62.4 / 73.1 / 73.5% | 87.5 / 93.7 / 96.5% | 0.64 / 0.64 / 0.65 |
| **ViT-S, 448 px** | **11** | **0.507** | **68.7 / 82.9 / 79.4%** | **93.0 / 96.0 / 98.8%** | **0.69 / 0.75 / 0.76** |

Increasing ViT-S resolution from 224 to 448 px adds 0.076 test mAP. Increasing
the backbone from ViT-S to ViT-B at 224 px adds 0.017 mAP at over three times
the per-step cost. Resolution was the larger gain. The 448 px ViT-S run is the
recommended checkpoint among these experiments.

New-tree rejection remains the weak point: at one photo, open-set balanced
accuracy is 0.37 zero-shot, 0.48 at 224 px, and 0.56 at 448 px. BarkNet was
collected in one summer, so these results measure same-season re-identification.

The test set has 383 query images across 35 known trees, so small metric
differences are noisy. Five-photo queries are formed by sampling, which is why
their top-1 can be lower than the three-photo score.

## Runtime

Measured on the RTX 3060, batch 64. Training times exclude validation.

| | ViT-S, 224 px | ViT-S, 448 px | ViT-B, 224 px |
|---|---:|---:|---:|
| Training | 20 min | 86 min | 39 min |
| Peak GPU memory | 1.3 GB | 4.5 GB | 2.8 GB |
| Step time | 0.112 s | 0.510 s | 0.376 s |

The ViT-S runs were data-loader bound. ViT-B was GPU bound. The 448 px config
uses two data workers because five-crop evaluation takes about 12 MB per image
and each extra worker costs roughly 2.9 GB of system RAM on this setup.

## Files

```text
configs/                  exact training/evaluation configs
zeroshot/                 four zero-shot eval JSONs
vits_224/                  224 px ViT-S training log and eval JSON
vits_448/                  448 px ViT-S training log and eval JSON
vitb_224/                  224 px ViT-B training log and eval JSON
```

Each `log.jsonl` contains the per-epoch training loss, training time, and
validation metrics. Each `eval_best.json` contains the validation and hemlock
test metrics for that run's best checkpoint.

