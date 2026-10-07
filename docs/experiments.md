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

## Update: production model v2 (`runs/reid/dino_plus_recapture`), trained with re-photographed trees

There is no public dataset of individual hemlocks photographed on different days. We searched BarkNet, the Harvard Forest archives (tagged hemlocks but no tree photos), PhenoCam (canopy only), iNaturalist (no individual identity) and bark datasets. So we used the closest available real data: **Laval Tree-Bark-Re-Identification** (Robert, Dallaire & Giguère, arXiv:1912.03221, MIT, [repo](https://github.com/ulaval-damas/Tree-Bark-Re-Identification)).

* 50 red pines + 50 elms, 2 bark patches per tree, 12 photos per patch.
* Each patch was **re-photographed** at night with the lamp and the phone (LG Q6) moved between shots. That is strong lighting and viewpoint change, but **a single session, not different days**.
* We split by tree: 20 train / 10 calibration / 20 test per species (`scripts/prepare_bark_reid.py`).
* Every number below is on the 40 **test** trees, which were never trained on or calibrated on (`scripts/evaluate_recapture.py`).

### E-recapture: does the model recognise a re-photographed tree?

Each query is 3 new photos of a patch; the gallery holds one earlier capture of surface 1 per enrolled tree (about 10 trees per species, so chance is about 10 %).

| Model | Red pine: same patch re-photographed, top-1 [CI] | Elm: same patch, top-1 [CI] | AUC same-patch vs wrong tree (RP / EL) | Other patch of same tree, top-1 (RP / EL) | Median cosine: same patch / wrong tree (RP) |
|---|---|---|---|---|---|
| DINOv2-S pretrained (no fine-tuning) | 0.39 [0.29, 0.48] | 0.40 [0.32, 0.49] | 0.685 / 0.625 | 0.13 / 0.26 | 0.982 / 0.974 |
| EfficientNetV2-M (MiewID recipe, BarkNet 2 ep) | 0.36 [0.27, 0.45] | 0.31 [0.24, 0.39] | 0.653 / 0.603 | 0.10 / 0.19 | 0.663 / 0.557 |
| DINOv2-S production v1 (BarkNet only) | 0.81 [0.74, 0.88] | 0.82 [0.73, 0.89] | 0.929 / 0.936 | 0.15 / 0.40 | 0.865 / 0.704 |
| **DINOv2-S v2 (BarkNet + 40 re-photographed training trees)** | **1.00 [1.00, 1.00]** | **0.99 [0.97, 1.00]** | **0.9994 / 0.9998** | 0.19 / 0.40 | **0.779 / 0.294** |

**Conclusions.**
1. Training on BarkNet hemlocks/conifers already transfers to new trees, a new species (elm), a new phone and night lighting: 0.39 → 0.81.
2. Adding genuinely re-photographed training trees teaches the model what stays the same about a tree when the light and angle change: 0.81 → 0.99–1.00. Wrong trees are pushed far apart (median cosine 0.70 → 0.29).
3. The model recognises a **bark patch**, not a whole trunk. A *different* patch of the same tree is barely recognised (0.19 / 0.40). This confirms the protocol design: every visit re-photographs the same patches (north side first, then fixed quarter-turns). It also shows the BarkNet "same tree, different region" numbers were partly driven by shared session cues (lighting, camera): the EfficientNetV2-M recipe that scored 0.77 on BarkNet scores 0.31–0.36 here.

### E-recapture-decision: are the automatic decisions safe in a new imaging condition?

The app's `fusion.decide` was run on the same test queries. Cells give auto-recognised correctly / wrong existing ID / new / uncertain:

| Model + calibration | Same patch re-photographed (RP) | Same patch (EL) | **New trees wrongly matched** (RP / EL) |
|---|---|---|---|
| v1 + BarkNet calibration (shipped) | 67 / 9.5 / 0 / 23 % | 67 / 5.8 / 2.3 / 25 % | **42 % / 19 %** |
| v1 + calibration on this camera (10 trees/species) | 24 / 0.2 / 63 / 13 % | 55 / 0.8 / 31 / 13 % | 0.2 % / 2.3 % |
| v2 + its BarkNet calibration (shipped) | 35 / 0 / 43 / 22 % | 65 / 0 / 14 / 21 % | **0 % / 0 %** |
| **v2 + calibration on this camera** | **87 / 0 / 8.5 / 4.2 %** | **96 / 0.2 / 0.2 / 3.7 %** | 0.75 % / 4.8 % |

**Conclusions.**
* Thresholds do **not** transfer across cameras and lighting for a model that has not learned invariance. v1 with BarkNet thresholds would have merged 19–42 % of new trees into existing IDs. **Always calibrate on the deployment camera.** `scripts/export_field_data.py` + `scripts/calibrate.py` do this from the app's own database.
* v2 is safe even with mismatched thresholds (0 % false matches), and with on-camera calibration it auto-recognises 87–96 % of re-photographed trees.

### v2 on the original hemlock test (no regression) and species gate

| Hemlock test (BarkNet, 14 trees) | v1 | **v2** |
|---|---|---|
| Image top-1 / mAP | 0.832 / 0.581 | 0.854 / 0.573 |
| 3-view top-1 [CI] / top-5 | 0.860 [0.71, 0.97] / 0.997 | 0.872 [0.77, 0.97] / 0.992 |
| 5-view top-1 | 0.941 | 0.928 |
| All-pairs AUC / strict no-overlap top-1 | 0.975 / 0.817 | 0.966 / 0.826 |
| AUC vs same-phone impostors | 0.912 | 0.895 (less reliance on camera cues) |
| Oracle open-set: returning trees accepted at 1 % / 10 % new-tree FMR, 3 views | 0.39 / 0.64 | 0.41 / 0.55 |
| … 5 views | 0.67 / 0.90 | 0.45 / 0.78 |
| Shipped decision (all-species BarkNet calibration): auto-accepted / FMR new trees | 43 % / 0.57 % | 15 % / 0 % |
| Species accuracy / hemlock precision / recall | 0.934 / 0.990 / 0.990 | **0.942 / 1.000 / 0.970** |
| Red spruce (never seen) called hemlock | 1 of 236 | **0 of 236** |

On BarkNet's same-session hemlocks, ranking is unchanged within noise, and v2's BarkNet-fitted thresholds are more conservative. The 5-view, 1 %-FMR oracle point is lower. Because BarkNet rewards session cues that will not exist on real revisits, we judged v2's re-photograph robustness the more relevant property.

**Decision: v2 is the production model.** Its thresholds must be re-fitted on field data.

* Training: `train_tail.py --cache runs/cache_dinov2 --extra-cache runs/cache_dinov2_barkreid --extra-data runs/data_barkreid --epochs 3`, with 156 identities and 705 steps (matched to v1's 700).
* Deployed ONNX path: hemlock test top-1 0.851 / mAP 0.572. Torch↔ONNX min cosine 0.99999988.
* Real-model end-to-end app test passes:
  * 5 hemlock revisits: 3 auto-recognised, 1 "uncertain", 1 registered as new with the true tree as second candidate.
  * 3 unenrolled hemlocks → new.
  * 3 red spruces → rejected.
  * No wrong IDs.

### What this still does not test

**Different days and seasons on hemlocks.** Laval is one night per tree; BarkNet is one day per tree. The pipeline for that test is built:
* `scripts/export_field_data.py` turns the app's database into a dataset where the session is the capture date.
* `scripts/evaluate_field.py` enrols each tree on its first day and queries later days, reporting accuracy by days elapsed (≤7 d, 8–60 d, 61–180 d, >180 d).

It is covered by an integration test on simulated multi-day visits. It needs your field data to produce real numbers.

## Previous headline: production model v1 (`runs/reid/dino_deep_multi`)

**Configuration.**
* DINOv2-S/14 at 322 px: blocks 0–7 frozen (cached, 4 augmentations per training image); blocks 8–11, final norm, GeM (p learned) and BN (384-d) fine-tuned.
* Sub-center ArcFace (k=3, dynamic margins 0.2–0.5, s=30) on the 116 multispecies training identities.
* 4 epochs, P×K = 16×4, Adam (1e-4 backbone / 1e-3 head), warm-up + cosine. Best hemlock val mAP 0.652 (epoch 4).
* Training took 102 min on 4 vCPU (CPU only, sharing the machine with other jobs).

Results on hemlock **test** trees (14 trees, never used for training, selection or calibration):

| Metric | EfficientNetV2-M deep (2 ep), the MiewID baseline | **DINOv2-S production** |
|---|---|---|
| Image one-vs-all top-1 / mAP | 0.696 / 0.428 | **0.832 / 0.581** |
| 3-view closed-set top-1 [95 % CI by tree] / top-5 (~7-tree gallery) | 0.769 [0.60, 0.88] / 0.970 | **0.860 [0.71, 0.97] / 0.997** |
| 5-view top-1 [CI] | 0.798 [0.63, 0.95] | **0.941 [0.88, 1.00]** |
| 1-view top-1 | 0.499 | 0.600 |
| Strict no-overlap regime top-1 | 0.743 | **0.817** |
| Queries from a different capture event (n=54, 3 trees) | 0.50 | **1.00** |
| All-pairs ROC-AUC / best-wrong-tree AUC | 0.921 / 0.734 | **0.975 / 0.883** |
| AUC vs same-phone / cross-phone impostors | 0.803 / 0.902 | **0.912 / 0.948** |
| Other species' test trees (pooled), image top-1 / mAP | 0.865 / 0.546 | **0.941 / 0.678** |
| Calibrated `decide()`, 1 % target (all-species val): returning trees auto-accepted | 7.5 % | **43.0 %** |
| … false-match rate (all queries / new trees) | 0.0 % / 0.0 % | **0.33 % / 0.57 %** (precision 98.2 %) |
| … returning trees routed to "uncertain → take more views" | 7.0 % | 26.2 % |
| Species: closed-set accuracy / macro-F1 | 0.930 / 0.932 | **0.934 / 0.938** |
| Species: hemlock precision / recall | 0.948 / 0.911 | **0.990 / 0.990** |
| Species: red spruce (never seen) rejected / called hemlock | 89.0 % / 5 of 236 | **97.0 % / 1 of 236** |
| ONNX file / peak RAM / inference per view (dev CPU, 4 threads) | 204 MB / 482 MB / 54 ms | **87 MB / 273 MB / 75 ms** |

**Real-model end-to-end run** (`tests/end_to_end/test_real_model.py`, through the app's HTTP API with the exported ONNX model and calibration):
* Enrolled 5 test hemlocks as H-001…H-005.
* Revisiting them with three different photos gave 4 auto-recognised (P = 0.90–0.99). One fell below the threshold and was registered as a duplicate (H-006); its true tree was the top candidate, so one-tap correction fixes it.
* 3 never-enrolled hemlocks → new IDs.
* 3 red spruces → "unknown, retake / not supported".
* No wrong existing ID was ever assigned.

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

## E-views: does multi-view actually help? (`evaluate_reid.py`, aggregation ablation; EfficientNetV2-M 2 ep, production numbers in the headline)

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
| EffNetV2-M, 3 views | 0.13 | 0.19 | 0.30 | 0.36 | 0.55 |
| EffNetV2-M, 5 views | 0.25 | 0.25 | 0.47 | 0.52 | 0.65 |
| **DINOv2-S (production), 3 views** | 0.39 | 0.45 | 0.53 | 0.64 | 0.74 |
| **DINOv2-S (production), 5 views** | **0.67** | 0.67 | **0.69** | **0.90** | 0.94 |

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

Repeated on the production DINOv2-S embeddings:

| Aggregator | Params | Test top-1 | Val top-1 | Best-wrong AUC (test) | Latency/obs |
|---|---|---|---|---|---|
| **Mean** | 0 | 0.860 | **0.959** | **0.883** | ~0 |
| Attention pooling | 49 k | 0.885 | 0.939 | 0.867 | 0.07 ms |
| 2-layer transformer | 1.25 M | 0.874 | 0.957 | 0.848 | 0.46 ms |

**Decision:** keep the mean. On test, attention pooling is +0.025 top-1, well inside the CI. But it is worse on validation, which is where model selection happens, and worse on AUC (the open-set decision). Neither learned aggregator justifies its parameters.

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

Hemlock **test** trees; 95 % CI over trees in brackets. "Steps" = optimiser steps.

| Run (one change vs reference) | Steps | Val img mAP | Test img top-1 / mAP | Test 3-view top-1 | All-pairs AUC | Strict top-1 | Diff.-capture top-1 (n=54) | Same-phone AUC |
|---|---|---|---|---|---|---|---|---|
| **Reference**: EffNetV2-M, sub-center ArcFace, 116 multispecies ids, seed 0 | 700 | 0.371 | 0.548 / 0.270 | 0.502 [0.31, 0.67] | 0.797 | 0.427 | 0.15 | 0.615 |
| … seed 1 (seed noise) | 700 | 0.363 | 0.519 / 0.269 | 0.535 [0.35, 0.70] | 0.802 | 0.442 | 0.19 | 0.619 |
| Loss: standard ArcFace (k=1, m=0.5) | 700 | 0.384 | 0.525 / 0.276 | 0.544 [0.35, 0.72] | 0.804 | 0.476 | 0.19 | 0.620 |
| Loss: supervised contrastive (τ=0.1) | 700 | 0.387 | 0.563 / 0.294 | 0.565 [0.33, 0.71] | 0.794 | 0.524 | 0.00 | 0.556 |
| Loss: batch-hard triplet (m=0.2) | 700 | 0.381 | 0.604 / 0.290 | 0.549 [0.31, 0.70] | 0.790 | 0.497 | 0.07 | 0.587 |
| Identities: hemlock only (22), same epochs | 125 | 0.343 | 0.389 / 0.215 | 0.383 [0.24, 0.51] | 0.738 | 0.314 | 0.48 | 0.649 |
| Identities: hemlock only (22), **equal steps** | 688 | 0.421 | 0.525 / **0.303** | **0.584** [0.39, 0.74] | **0.837** | **0.537** | **0.67** | **0.716** |
| **Backbone: DINOv2-S/14** (322 px), multispecies, seed 0 | 700 | **0.590** | **0.791 / 0.536** | **0.804** [0.67, 0.94] | **0.941** | **0.732** | **0.89** | **0.882** |
| … DINOv2-S/14, seed 1 (seed noise) | 700 | 0.581 | 0.817 / 0.539 | 0.796 | 0.940 | 0.722 | 1.00 | 0.882 |
| … DINOv2-S/14, hemlock-only identities, equal steps | 688 | 0.586 | 0.766 / 0.516 | 0.810 [0.68, 0.94] | 0.940 | 0.765 | 0.94 | 0.889 |

**Conclusions.**
* **Loss.** Sub-center ArcFace, ArcFace, SupCon and Triplet are within seed noise of each other on the main metrics (the two reference seeds differ by 0.03 in top-1, and all CIs overlap). SupCon and Triplet are worst on the same-phone and cross-capture checks (0.00 and 0.07 cross-capture top-1 with n=54 from 3 trees; small, but in the wrong direction). There is no evidence to move away from the MiewID objective, so sub-center ArcFace stays.
* **Multispecies.** At equal optimiser steps, training on the 22 hemlock identities alone is *at least as good* for hemlock re-ID as training on 116 multispecies identities.
  * EfficientNetV2-M: hemlock-only is better on the harder metrics.
  * DINOv2-S: the two are equivalent within noise.
  * MiewID's multispecies gain (49 animal species, 37K individuals) **did not reproduce** at this scale, and the apparent multispecies advantage at equal epochs is a step-count artefact.
  * **Decision:** keep multispecies identities for the production model anyway. They cost nothing in re-ID accuracy with DINOv2, and the same embedding drives the species gate, which needs other species to be separated.
* **Backbone.** In an identical regime and budget, DINOv2-S beats EfficientNetV2-M by a margin far beyond seed noise: test mAP 0.536 vs 0.27, and 3-view top-1 0.80 vs 0.50–0.54. It is also more robust exactly where it matters for field use: different capture events (0.89 vs 0.15) and same-phone impostors (0.88 vs 0.61). It is 2.4× smaller (22 M vs 53 M params). **Decision: the primary backbone becomes DINOv2-S/14**, keeping MiewID's GeM → BN head and sub-center ArcFace. EfficientNetV2-M remains supported in code for reproduction.

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

With the production DINOv2-S embedding, the test numbers are:
* closed-set accuracy 0.934, macro-F1 0.938
* accuracy with rejection 0.894; 7.8 % of known-species observations rejected
* red spruce rejected **97.0 %**, called hemlock **1 / 236**
* hemlock precision / recall **0.990 / 0.990**
* threshold 0.669; Thuja rejection on validation 96.1 %

EfficientNetV2-M table above: validated threshold 0.617 (validation: Thuja rejection 92.2 %). Confusions that
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

Repeated on the production DINOv2-S embeddings:
* global alone: test AUC 0.959
* fused without local: **0.9674**
* fused with local: 0.9677

Cost on the dev machine (EfficientNet run): 42 ms extraction per view and 30 ms per view-pair match (≈1.4 s per identification for top-5 × 9 pairs), plus 54 KB per view of stored descriptors.

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
| **DINOv2-S production**, all species' val (shipped `calibration.json`) | **43.0 %** | **0.33 %** | **0.57 %** | 26.2 % (new trees: 11.4 %) |
| DINOv2-S, hemlock val only | 53.1 % | 3.2 % | 5.2 % | 17.5 % |
| DINOv2-S, global cosine only, gallery-size-aware threshold | 41.4 % | 1.5 % | 1.7 % | – |
| DINOv2-S, global cosine only, best-wrong-tree threshold | 53.8 % | 4.2 % | 5.3 % | – |

The first three rows are the EfficientNetV2-M (2 ep) model.

**Conclusions.**
* The DINOv2-S model with the logistic fuser and all-species calibration is the shipped configuration. It holds the false-match rate at 0.33 % on test, close to the 1 % target and on the safe side, while auto-accepting 43 % of returning trees.
* The *gallery-size-aware* threshold transfers better than the plain best-wrong-tree threshold: 1.7 % vs 5.3 % FMR on new trees, for a 1 % target.
* For the EfficientNetV2-M model: with 9 validation hemlocks, a 1 % operating point cannot be estimated reliably. The hemlock-only calibration overshot (4.3 % FMR on new trees).
* Pooling all species' validation trees gives a conservative threshold that held the FMR at 0 on test.
* At a true ~1 % FMR, the EfficientNetV2-M model auto-recognised only **5–17 %** of returning trees (top-1/top-5 77 % / 97 %). DINOv2-S raised this to 43 %.

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

**Conclusion.** The metrics reproduce within noise. The decode difference was a small train/serve skew.

**Fix applied for production.** `decode_image` now decodes JPEGs with libjpeg DCT scaling (Pillow `draft`) to the smallest 1/2ⁿ scale with short side ≥ 640 px. That is the same scale the training cache used. For the DINOv2-S production model through the deployed path:

| | Test img top-1 / mAP | Test 3-view top-1 | All-pairs AUC |
|---|---|---|---|
| Training-cache embeddings | 0.832 / 0.581 | 0.860 | 0.975 |
| Deployed ONNX path | 0.829 / 0.581 | 0.858 | 0.975 |

Per-image cosine between the two paths is now median 1.000, min 0.977 (it was min 0.806 before the fix). Torch vs ONNX parity: min cosine 0.99999994.

## E-efficiency (`benchmarks/`)

Dev machine: x86-64 cloud container, 4 vCPU, no GPU. **Not a Raspberry Pi** (none was available); see deployment.md for how to measure on the device. Each runtime runs in a fresh process; peak RSS includes the Python runtime. Medians are over 5 BarkNet photos (2220×3830 JPEG) × 3 repeats.

| Runtime (threads) | Model file | Load | Decode | Preprocess | Inference | **Per view** | 3 views | Peak RSS |
|---|---|---|---|---|---|---|---|---|
| **DINOv2-S ONNX FP32 (4) — production** | 87 MB | 0.30 s | 37 ms | 4 ms | 75 ms | **117 ms** | 0.35 s | **273 MB** |
| DINOv2-S ONNX FP32 (1) | 87 MB | 0.26 s | 39 ms | 5 ms | 234 ms | 278 ms | 0.83 s | 272 MB |
| DINOv2-S Torch (4) | 87 MB | 2.49 s | 38 ms | 4 ms | 66 ms | 108 ms | 0.32 s | 536 MB |
| EfficientNetV2-M ONNX FP32 (4) | 204 MB | 0.55 s | 30 ms | 4 ms | 54 ms | 88 ms | 0.26 s | 482 MB |
| EfficientNetV2-M ONNX FP32 (1) | 204 MB | 0.49 s | 31 ms | 5 ms | 187 ms | 222 ms | 0.67 s | 480 MB |

**12 MP phone photo (4032×3024)**, DINOv2-S ONNX (4 threads):

| Decode | Decoded size | Decode | Per view | Peak RSS |
|---|---|---|---|---|
| Full resolution (before) | 4032×3024 | 164 ms | 259 ms | 425 MB |
| **DCT-scaled (production)** | 1008×756 | **45 ms** | **129 ms** | **229 MB** |

**Gallery search + storage** (`bench_retrieval.py`; 4 observations per tree, 3 views + aggregate per query):

| Gallery | 100 trees | 1,000 trees | 5,000 trees |
|---|---|---|---|
| 384-d (production): search / RAM | 0.09 ms / 0.6 MB | 0.43 ms / 6.1 MB | 2.1 ms / 31 MB |
| 2152-d (EffNet): search / RAM | 0.22 ms / 3.4 MB | 1.6 ms / 34 MB | 9.2 ms / 172 MB |

The first index version (fp16 in RAM + `np.maximum.at`) needed 40 ms for 400 observations. It was replaced by an fp32 matrix + `reduceat`.

Storage per 3-view observation: about 5 KB in SQLite (fp16 embeddings + metadata), plus the original JPEGs, stored once and content-addressed. Local keypoints, if enabled, add 54 KB per view.

**Conclusions.**
* Image inference dominates. Retrieval and the decision are milliseconds even at 5,000 trees.
* On this x86 CPU, DINOv2-S is *not* faster than EfficientNetV2-M (75 vs 54 ms with 4 threads). Its advantages are accuracy, a 2.3× smaller file and 43 % less RAM.
* JPEG decode was the largest avoidable cost for phone photos. DCT-scaled decode halved per-view time and RAM with no accuracy change (E-deploy).

## E-duplicate: detecting re-shot views (`scripts/calibrate_duplicate.py`)

Production model. Re-shoots were simulated with small camera jitter on 116 training trees; "next views" are other photos of the same tree.

| | p1 | p5 | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| Re-shoot cosine | 0.718 | 0.777 | 0.891 | | | |
| Next-view cosine | | | 0.645 | 0.820 | 0.886 | 0.915 |

The two distributions **overlap**, so embedding similarity cannot reliably detect re-shoots on bark. The first attempt rejected views above the 99th percentile of next views. That wrongly rejected a genuine view in the real-model end-to-end test, which became a regression test.

**Decision:**
* **Reject** only near-identical captures (cosine > 0.97, above the maximum genuine value of 0.915).
* **Warn** above 0.886 ("did you move?").
* Use the **compass**: consecutive rotation views must differ by ≥ 30° of heading, otherwise the view is rejected with "walk a quarter-turn around the tree". This is cheap and explainable, and it catches what the embedding cannot.

## Open blockers / not done

* **No multi-day hemlock data.** Same-tree / later-day and cross-season re-identification cannot be measured with any open dataset we found. Re-photographing under changed lighting was tested (E-recapture), and the export + later-day evaluation pipeline is ready for field data.
* **No canopy/branching training data** with individual labels. Those views are stored but excluded from identity.
* **No Raspberry Pi or depth camera was available.** All latencies are from the dev machine, and the device adapters (`acquisition/devices.py`) are untested on hardware.
* **Training budget.** CPU only, so DINOv2 blocks 0–7 stay frozen, and the loss/identity ablations used the cheaper last-block regime with 1–2 seeds. End-to-end fine-tuning on a GPU, with more seeds, is the obvious next experiment.
* **Small test set.** 14 test hemlocks. CIs on observation top-1 are about ±0.13.
* **INT8 for DINOv2-S** has not been evaluated; INT8 was only tested on EfficientNetV2-M, where it lost accuracy.
