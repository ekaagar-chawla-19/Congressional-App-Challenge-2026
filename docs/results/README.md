# Raw results

JSON written by the scripts in this repository (copied from `runs/results`,
`runs/species`, `runs/bench`). They are the source for the numbers in
[`../experiments.md`](../experiments.md). Regenerate them with the commands in the top-level README.

| File pattern | Produced by | Experiment |
|---|---|---|
| `pretrained.json`, `deep_subcenter_2ep.json`, `dino_deep_multi.json` | `scripts/evaluate_reid.py` | E-pretrained/finetuned, E-views, headline |
| `lb_*.json` | `scripts/run_ablations.sh` | E-ablations (last-block regime) |
| `zero_shot.json` | `scripts/zero_shot_backbones.py` | E-backbone |
| `aggregators_*.json` | `training/reid/train_aggregator.py` | E-aggregation |
| `local_*.json` | `scripts/evaluate_local.py` | E-local |
| `decision_*.json`, `calibration_production.json` | `scripts/calibrate.py` | E-decision (the latter is what the app loads) |
| `curve_*.json` | `scripts/operating_curve.py` | operating curves (oracle) |
| `species_*.json` | `training/species/train_head.py` | E-species |
| `onnx_*.json` | `embed_with_runtime.py` + `evaluate_reid.py` | E-deploy, E-quantisation |
| `overlap.json` | `scripts/analyze_overlap.py` (pair list removed) | E-overlap |
| `depth.json` | `scripts/evaluate_depth.py` | E-depth |
| `duplicate_*.json` | `scripts/calibrate_duplicate.py` | E-duplicate |
| `quality_calibration.json` | `scripts/calibrate_quality.py` | E-quality |
| `history_*.json` | `training/reid/train_tail.py` | training curves (val) |
| `recapture_*.json` | `scripts/evaluate_recapture.py` | E-recapture (Laval re-photographed trees) |
| `bench/*.json` | `benchmarks/` | E-efficiency |

`deep_subcenter_2ep` = EfficientNetV2-M (MiewID baseline), stage 5 fine-tuned, 2 epochs.
`dino_deep_multi` = production v1, DINOv2-S/14, blocks 8–11 fine-tuned, 4 epochs (`calibration_v1.json`).
`dino_plus_recapture` = production v2, v1 recipe + 40 re-photographed Laval training trees, 3 epochs (`calibration_production.json`).
