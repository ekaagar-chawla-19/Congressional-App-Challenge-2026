# Experiment log

Every number below was produced by a script in this repository on the stated
split. The raw JSON is written to `runs/results/` (not committed: regenerate with
the commands in the README). If an experiment could not be run, it says so.

## Data, splits and protocol (applies to every re-ID number)

* **Data.** BarkNet 1.0 (Zenodo 11508014, MIT). Ten species were used.
  * Trained on: hemlock PRU, white pine PIB, red pine PIR, pitch pine PID, beech HEG, red maple ERR, Norway maple ERB, bigtooth aspen PEG.
  * Held out entirely: Thuja (THO, used for validation of unknown-species rejection) and red spruce (EPR, used for its test).
  * In total 6,864 images.
* **Identity-disjoint splits** (`scripts/prepare_barknet.py`, seed 17). Trees, not images, are split 50/20/30 per species. Hemlock: **22 train / 9 val / 14 test trees**. Species with fewer than 5 trees are train-only. Training identities are the 116 training trees of all eight species.
* **Regime.** BarkNet photographs each tree in **one session**: about 22 bark photos around the trunk, 1–2 capture events, same day. Everything here is therefore *same tree / new bark region / same session*. **Cross-session and cross-season re-ID is untested** (no such data for hemlocks was found).
* **Observations.** A tree's images are partitioned into disjoint simulated captures of V=3 views (101 test and 53 val observations).
* **Open-set protocol** (`evaluation/benchmarks.py`). 20 random enrolments. In each, half the trees are enrolled with one observation: about 7 test or 4–5 val trees in the gallery. Their other observations are *known* queries, and all observations of the other half are *new-tree* queries. Test has 759 known and 1,061 new-tree queries.
* **Thresholds** are fitted on **val** and applied unchanged to test. Test trees are never used for training, selection or calibration. The exception is curves explicitly labelled *oracle*.
* **Uncertainty.** The test set has 14 trees. 95 % CIs bootstrap over trees (queries of one tree are correlated), and they are wide.

## E-overlap: data-leakage audit (`scripts/analyze_overlap.py`)

**Hypothesis.** Different BarkNet images of one tree are different bark regions, so no near-duplicates exist.

**Result.** Partly false.
* The threshold is RootSIFT+RANSAC inliers above the 99.9th percentile of different-tree pairs (6 inliers).
* **5.9 % of same-tree image pairs overlap.** All 23 val+test trees have at least one overlapping pair.

**Consequence.** A *strict* regime (below) drops every known query that shares overlapping content with the enrolled observation (202 of 759 test queries). Both regimes are reported.

## E-pretrained vs E-finetuned: does fine-tuning learn individual identity?

Same architecture (EfficientNetV2-M → GeM → BN, 320 px). The first row is pretrained ImageNet weights. The second fine-tunes stage 5 + conv_head + GeM + BN with sub-center ArcFace (k=3, dynamic margins 0.2–0.5, s=30) for 2 epochs on cached trunk features (`train_tail.py`, P×K = 16×4, Adam 1e-4/1e-3, cosine). It was selected on val mAP.

| Metric (hemlock **test**, trees unseen in training) | Pretrained | Fine-tuned (2 ep) |
|---|---|---|
| Image one-vs-all top-1 / mAP | 0.297 / 0.157 | **0.696 / 0.428** |
| 3-view observation, closed-set top-1 (~7-tree gallery) | 0.229 [0.09, 0.35] | **0.769 [0.60, 0.88]** |
| … top-5 | 0.850 | 0.970 |
| … strict no-overlap regime top-1 | 0.201 | **0.743** |
| … queries from a *different capture event* (n=54) | 0.037 | 0.500 |
| ROC-AUC, genuine vs every wrong tree | 0.620 | **0.921** |
| ROC-AUC, genuine vs best wrong tree per query | 0.278 | 0.734 |
| AUC vs impostors from the **same phone** / other phones | 0.525 / 0.642 | 0.803 / 0.902 |
| Other species' test trees, image top-1 / mAP | 0.363 / 0.126 | 0.865 / 0.546 |

**Conclusions.**
* Fine-tuning learns individual identity that generalises to unseen hemlocks.
* Pretrained features mainly encode the **camera**: same-device AUC is 0.52, i.e. chance.
* The fine-tuned model still benefits from shared camera and lighting (same-device AUC 0.80 vs 0.90). A query from a different capture event is much harder (0.50 vs 0.79). **Real repeat visits with different phones and seasons will be harder than these numbers.**

## E-views: does multi-view actually help? (`evaluate_reid.py`, aggregation ablation, fine-tuned 2 ep)

| Query/gallery construction | Test top-1 [95 % CI] | All-pairs AUC |
|---|---|---|
| 1 view (first view only) | 0.489 [0.39, 0.70] | 0.780 |
| 3 views, mean of normalised embeddings (**production**) | **0.769** [0.60, 0.88] | 0.921 |
| 3 views, late fusion (max over view pairs) | 0.614 [0.51, 0.77] | 0.907 |
| 5 views, mean | **0.798** [0.63, 0.95] | 0.944 |

Open-set operating curve (**oracle** sweep on test, for choosing a target only;
`scripts/operating_curve.py`). Fraction of returning trees auto-accepted at a
given false-match rate on new trees:

| FMR on new trees | 1 % | 2 % | 5 % | 10 % | 20 % |
|---|---|---|---|---|---|
| 3 views | 0.13 | 0.19 | 0.30 | 0.36 | 0.55 |
| 5 views | 0.25 | 0.25 | **0.47** | 0.52 | 0.65 |

**Conclusion.** Multi-view aggregation is real and large: 1→3 views gives +0.28 top-1. The mean beats late fusion. Five trunk views raise open-set acceptance substantially. **Decision:** when an identification is uncertain, the app asks for *extra trunk views* (not the branching/canopy views).

## E-aggregation: learned multi-view fusion vs mean (`train_aggregator.py`)

Trained on train-tree per-view embeddings (SupCon on aggregated vectors, 400
steps) and evaluated on test.

| Aggregator | Params | Test top-1 | Val top-1 | Best-wrong AUC | Latency/obs |
|---|---|---|---|---|---|
| **Mean (production)** | 0 | **0.769** | 0.842 | **0.734** | ~0 |
| Attention pooling | 276 k | 0.738 | 0.847 | 0.720 | 0.10 ms |
| 2-layer transformer (d=256) | 2.16 M | 0.688 | 0.842 | 0.695 | 0.92 ms |

The transformer accepted 40 % of returning trees at the val-fitted threshold, but at an 11 % test false-match rate; the target was 1 %. That is a threshold-transfer artefact, not a better trade-off.

**Decision:** keep the mean. Neither learned aggregator justifies its parameters.

## E-backbone (zero-shot): which pretrained features are most individual-discriminative? (`zero_shot_backbones.py`)

Frozen weights → GeM(p=3) → L2, with no fine-tuning, on hemlock trees.

| Backbone (weights) | Val img top-1 / mAP | Test img top-1 / mAP | Test 3-view top-1 |
|---|---|---|---|
| EfficientNetV2-M (ImageNet-1k) | 0.353 / 0.250 | 0.297 / 0.157 | 0.229 |
| MiewID-msv3 (EffNetV2-M, wildlife re-ID) | 0.506 / 0.240 | 0.465 / 0.203 | 0.410 |
| ConvNeXt-T (IN-22k→1k) | 0.553 / 0.328 | 0.481 / 0.253 | 0.406 |
| Swin-T (IN-1k, 224 px) | 0.618 / 0.365 | 0.551 / 0.280 | 0.503 |
| DINOv2-S/14 (LVD-142M, 322 px) | **0.647 / 0.344** | **0.652 / 0.316** | **0.528** |

**Conclusion.** Zero-shot, ImageNet EfficientNetV2-M is the *worst* of these on bark, and MiewID's animal re-ID weights do not transfer well either. The zero-shot ranking does not decide the production backbone, because fine-tuned EfficientNetV2-M (0.769) is far above every zero-shot number. It does justify a **controlled fine-tuned comparison** with DINOv2-S (E-ablations).

## E-ablations: loss, multispecies, backbone (controlled, `scripts/run_ablations.sh`)

**Regime.** For CPU budget, only the backbone's **last block + final layers +
GeM + BN** are trained, on a second-level feature cache. That is about 2.3 M
trainable params for EfficientNetV2-M and 1.8 M for DINOv2-S. Each run uses 4
epochs, the same sampler, schedule and seed, and changes one variable relative
to the sub-center ArcFace reference.

These are *relative* comparisons in a shallow fine-tuning regime. They are not
the production model's numbers.

(results table: see the section filled in below)

## E-species: species gate on the shared embedding (`training/species/train_head.py`)

Multinomial logistic regression on the L2-normalised re-ID embedding (= one
`Linear` in the deployed model). C was chosen on val accuracy. The unknown
threshold maximises balanced accuracy on val known-species vs Thuja (never
trained). It was tested on test trees and on **red spruce**, which was never used
anywhere. Decisions are per 3-view observation.

| Test metric | Pretrained embedding | Fine-tuned embedding (production) |
|---|---|---|
| Closed-set accuracy / macro-F1 (5 species with test trees) | 0.823 / 0.845 | **0.930 / 0.932** |
| Accuracy with unknown rejection | 0.695 | **0.886** |
| Known-species observations rejected as "unknown" | 18.9 % | 7.0 % |
| Red spruce (never seen) rejected as "unknown" | 64.8 % | **89.0 %** |
| Red spruce observations called **hemlock** | 43 / 236 | **5 / 236** |
| Hemlock precision / recall | 0.575 / 0.723 | **0.948 / 0.911** |

Validated threshold: 0.617 (validation: Thuja rejection 92.2 %). Confusions that
remain are mostly red maple → beech (25 of 171 red-maple observations).

**Conclusion.** One shared backbone serves both tasks, with no second network. The
red-spruce result shows the gate is not perfect for look-alike conifers.

## E-local: does bark keypoint matching add evidence? (`scripts/evaluate_local.py`)

Pairs are (query, top-5 global candidate), with 5 enrolments. A logistic fuser was fitted on val pairs (980) and tested on test pairs (2,250, 181 genuine).

| | Test AUC |
|---|---|
| Local score alone (RootSIFT+RANSAC, best of 3×3 view pairs) | 0.665 |
| Global cosine alone | 0.885 |
| Fused: global + gap + agreement | **0.892** |
| Fused: global + gap + agreement + local | 0.890 |

Cost on the dev machine: 42 ms extraction per view and 30 ms per view-pair match (≈1.4 s per identification for top-5 × 9 pairs), plus 54 KB per view of stored descriptors.

**Decision:** local matching is **off by default**. It adds no information over the
fine-tuned embedding on this data, where the views of one tree are mostly
different bark regions. The capture protocol anchors view 1 to the north side so
repeat visits overlap; re-test on field data.

## E-decision: calibrated end-to-end decision on test (`scripts/calibrate.py`)

Thresholds and the logistic fuser (global, gap, agreement) were fitted on val at a
1 % target false-match rate, then evaluated with the app's `fusion.decide` on test
(fine-tuned 2-ep embeddings, 3 views).

| Calibrated on | Returning trees auto-accepted | False-match rate (all queries) | FMR on new trees | Returning trees → "uncertain" (asks for more views) |
|---|---|---|---|---|
| Hemlock val only (9 trees) | 17.0 % | 2.5 % | 4.3 % | 13.3 % |
| All species' val trees (5,620 trials) | 7.5 % | 0.0 % | 0.0 % | 7.0 % |
| Global cosine only, hemlock val | 7.8 % | 0.0 % | 0.0 % | – |

**Conclusions.**
* With 9 validation hemlocks, a 1 % operating point cannot be estimated reliably. The hemlock-only calibration overshot (4.3 % FMR on new trees).
* Pooling all species' validation trees gives a conservative threshold that held the FMR at 0 on test.
* At a true ~1 % FMR, the current model auto-recognises only **5–17 %** of returning trees, even though their top-1 / top-5 ranking accuracy is 77 % / 97 %.

**Decision:** run as **assisted identification**.
* Auto-accept only above the calibrated threshold.
* Otherwise show the ranked candidates for one-tap confirmation (`/api/session/{id}/correct`), and request extra trunk views when views contradict.

Gallery-size-aware thresholds (`threshold_for_gallery`) are implemented and unit-tested, but give the same operating point here.

## E-depth: is structural evidence from depth worth having? (`scripts/evaluate_depth.py`)

*Part A, real tree sizes.* BarkNet records each tree's circumference. A gate
`|ΔDBH| ≤ 2.576·√2·σ` keeps 99 % of same-tree pairs.

| DBH measurement error σ | 0.5 cm | 1 cm | 2 cm | 3 cm | 5 cm |
|---|---|---|---|---|---|
| Different-hemlock pairs rejected (45 trees, 990 pairs) | 89 % | **77 %** | 57 % | 37 % | 14 % |

*Part B, SYNTHETIC trunks only.* `SimulatedDepth` uses DBH drawn from the real
hemlock DBHs and stereo-style noise σ(z)=a+bz² at 1.5 m.

| Point noise at 1.5 m | 0.1 cm | 0.66 cm | 1.2 cm | 2.35 cm |
|---|---|---|---|---|
| Median diameter error | 0.4 cm | 1.1 cm | 2.4 cm | 5.5 cm |
| Stem-profile same-vs-different AUC (30 trees) | 1.00 | 1.00 | 1.00 | 1.00 |

**Conclusion.** Part A (real data) shows that a depth-derived DBH check would remove most impostors **if** the device measures DBH to about 1–2 cm. Part B only shows the algorithm works on idealised trunks; synthetic trunks are far more regular and distinctive than real ones.

**Decision:** depth goes through `DepthProvider`, and the profile matcher is implemented and tested. Structure is **off by default** until it is calibrated on real field depth.

## E-quality: image-quality thresholds (`scripts/calibrate_quality.py`)

Measured on 200 BarkNet training images and their Gaussian-blurred copies (σ=3 px at 512 px):

| Metric | Sharp images, p1 | Blurred, p99 | Threshold |
|---|---|---|---|
| Laplacian variance | 74 | 8.3 | 25 (geometric mean) |
| Edge density | 0.089 | 0.041 | 0.06 |

Mean luminance of real images is 41–154 (p1–p99), and the clipped fraction is ≤ 0.08 (p99). The limits are set outside these ranges.

## E-quantisation: INT8 (`scripts/quantize_model.py`)

Evaluated through the deployed ONNX path on hemlock val/test. Activations were calibrated on 96 *training* images.

| Model | Size | Test img top-1 / mAP | Test 3-view top-1 | All-pairs AUC |
|---|---|---|---|---|
| FP32 ONNX (**production**) | 204 MB | **0.684 / 0.426** | **0.739** | **0.923** |
| INT8 static QDQ, all ops | 56 MB | 0.623 / 0.342 | 0.594 | 0.865 |
| INT8 static QDQ, Conv only | 56 MB | 0.646 / 0.378 | 0.685 | 0.899 |
| INT8 percentile calibration | – | ran out of memory (16 GB) | | |

**Decision:** **stay FP32.** Post-training INT8 costs 11–20 % of mAP. Revisit with quantisation-aware training if latency on the Pi requires it.

## E-deploy: does the exported model reproduce the training-time numbers?

ONNX vs Torch parity: min cosine 0.9999999 (`parity.json`).

The deployed path uses PIL full-resolution decode, the app's resize and ONNX Runtime. The training cache used an OpenCV half-resolution decode.

| | Test img top-1 / mAP | Test 3-view top-1 | All-pairs AUC |
|---|---|---|---|
| Training-cache embeddings | 0.696 / 0.428 | 0.769 | 0.921 |
| Deployed ONNX path | 0.684 / 0.426 | 0.739 | 0.923 |

Per-image cosine between the two paths: median 0.990, min 0.806.

**Conclusion.** The metrics reproduce within noise. The decode difference is a small train/serve skew, documented here; future caches should use `preprocessing.decode_image`.

## E-efficiency

See the section filled from `runs/bench/` below.

## Open blockers / not done

* **No temporal data.** Same-tree / later-session and cross-season re-identification cannot be measured with any open dataset we found. The app stores everything needed to build this dataset from field visits.
* **No canopy/branching training data** with individual labels. Those views are stored but excluded from identity.
* **No Raspberry Pi or depth camera was available.** All latencies are from the dev machine, and the device adapters (`acquisition/devices.py`) are untested on hardware.
* **Training budget.** CPU only, so stages 0–4 stay frozen. End-to-end fine-tuning on a GPU is the obvious next experiment.
