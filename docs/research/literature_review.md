# Literature review and design decisions

This file records, for each architecture decision, what the primary source did,
on what data, the result, what transfers to individual Eastern hemlock
re-identification, what does not, and what we decided. Numbers quoted from
papers are the papers' own; numbers from this project are in
[`../experiments.md`](../experiments.md).

**Evidence warning.** No paper we found re-identifies individual *Eastern
hemlocks*, or individual trees of any species, from handheld RGB photographs
across seasons. Every transfer below goes from animals, orchard trees, Scots pine
point clouds, or bark patches to our problem. Each one is a hypothesis we test,
not a proven fact.

---

## 1. MiewID — multispecies animal re-ID (primary architecture source)

*Otarashvili, Subramanian, Holmberg, Levenson, Stewart. "Multispecies Animal
Re-ID Using a Large Community-Curated Dataset", arXiv:2412.05602 (2024).* We read
the paper and its code (`WildMeOrg/wbia-plugin-miew-id`: `models/model.py`,
`models/heads.py`, `train.py`, `configs/default_config.yaml`).

| | |
|---|---|
| What they did | One embedding model for 49 species (37K individuals, 225K images); retrieval by cosine similarity against a gallery |
| Architecture (verified in code) | timm `efficientnetv2_rw_m` (ImageNet) → **GeM** (learnable p, init 3) → **BatchNorm1d** → embedding = backbone width (**2152-d**; no FC layer by default; the released msv3 config has `use_fc: false`) |
| Loss (verified in code) | **Sub-center ArcFace** (k sub-centres, class cosine = max over them) with **dynamic margins**: `tmp = sqrt(1/sqrt(n_c))` min-max scaled into `[0.2, m_max]`, so rarer identities get larger margins; scale s (paper 51.5; default config 30) |
| Training (paper) | 256×256 experiments (440×440 production); batch 112; linear warm-up 1.5e-5→1.5e-3 over 15 epochs then ×0.8/epoch decay; colour jitter, CLAHE, shift/scale/rotate augmentations; Optuna-tuned |
| Splits (paper) | Test set: 50 % of individuals also in training (different images), 50 % unseen; identities with <3 images dropped from training; ≤10 images and one image per encounter per test identity; one-vs-all evaluation |
| Results (paper) | Multispecies model beats species-specific models by 12.5 % top-1 on average; beats MegaDescriptor by 19.2 % top-1 averaged over 33 species; EfficientNetV2 beat a SwinV2-Base variant by 4.5 % on average |
| Applies to us | Embedding + cosine retrieval naturally handles new individuals (open set) without retraining a classifier. The architecture is a strong, efficient CNN (~53 M params, ~24 GMACs at 440 px) that runs on CPU. Multi-species training gives more identities for a margin loss. |
| Does not apply | Animals have distinctive coat/skin marks; bark is a much more homogeneous texture. Their test set mixes seen and unseen identities. A field instrument must handle **unseen** trees, so we evaluate only on identities that never appear in training. Their 225K images: we have ~3K training images. |
| **Decision** | Adopt MiewID's *head and objective*: GeM (p=3, learnable) → BN, embedding = backbone width, L2-normalised at retrieval, sub-center ArcFace with dynamic margins (k=3, m ∈ [0.2, 0.5], s=30). Our implementation guards two edge cases MiewID's does not: equal class counts (0/0 → NaN margins) and the infinite derivative of `sqrt(1-cos²)` at cos=±1, both with regression tests. **Two MiewID findings did not reproduce on bark** in our controlled experiments (experiments.md E-ablations). (1) EfficientNetV2-M was beaten by DINOv2-S at equal budget, so **the primary backbone is DINOv2-S/14**. (2) At equal optimiser steps, multispecies identities did not improve hemlock re-ID. |

Their HuggingFace model `conservationxlabs/miewid-msv3` has no license on its
model card. We use it only for a zero-shot comparison and do not ship it.

## 2. Scots pine architectural fingerprinting (TLS)

*Yrttimaa, Junttila, Hyyppä, Holopainen, Wulder, Vastaranta. "Quantifying
architectural uniqueness of Scots pine trees using terrestrial laser scanning:
toward individual tree fingerprinting", Forestry 98(4):465 (2025).*

| | |
|---|---|
| What they did | Scanned 65 Scots pines (boreal managed stand) in Sept 2021 and Nov 2022 with TLS; matched individuals across years using the **stem profile** (diameters every 10 cm by circle fitting, spline-smoothed, 1.0 cm tolerance) and **branch-origin patterns** (branch/stem intersections as (azimuth, height) point patterns, matched within 3 cm) |
| Results | 52/65 trees (80.0 %) identified; **100 % among the 20 trees with ≥10 re-observed branch origins**; 96.9 % with ≥5. Diameter observations: 87.7 % within 1 cm across a year, RMSE 0.4–0.7 cm. Failures had many branches, but few that were visible at both times |
| Why trees are distinctive | Micro-environment shapes each stem and branch arrangement uniquely. Lower-stem branch origins (live or dead, unpruned) are stable for years |
| Limitations (theirs) | Few trees, one species, one stand ("caution is required when interpreting universality"). Requires high-quality TLS, especially of the lower stem |
| Applies to us | Strong motivation that **geometry** (stem profile, branch arrangement) is an individual fingerprint that is stable across a year, which is exactly what seasonal colour/foliage changes do not disturb |
| Does not apply | Consumer depth (phone ToF/LiDAR, stereo) is not TLS. Branch origins at mm–cm accuracy are not recoverable from a single handheld depth frame. Hemlock branching differs from pine. |
| **Decision** | Use depth for the part that is plausibly measurable with consumer sensors: stem diameter profile / DBH consistency, matched with a tolerance (`local_matching.trunk_profile_from_depth`, `profile_similarity`). It is a candidate-level structural signal, not part of the neural network. On real BarkNet hemlock DBHs, a DBH-consistency gate with 1 cm measurement error would reject 77 % of different-tree pairs while keeping 99 % of same-tree pairs (E-depth). Branch-origin matching is future work that needs better 3-D capture (e.g. multi-frame fusion). |

## 3. Tree-SLAM (orchards, RGB-D)

*"Tree-SLAM: Semantic object SLAM for efficient mapping of individual trees in
orchards", arXiv:2507.12093 (2025).*

| | |
|---|---|
| What they did | Robot with an Intel RealSense D455 (1280×720) + RTK-GPS + IMU. YOLOv8 instance segmentation of trunks → trunk point clouds → **cascade-graph data association**: an image-space SORT-like stage, then neighbour-based propagation through the spatial relations between trees, with global association as fallback. Re-identified trunks become landmarks in a factor graph with GPS and odometry |
| Results | Geo-localisation error as low as 18 cm (<20 % of planting distance), across apple and pear orchards in different seasons |
| GPS | RTK-GPS degrades badly under canopy. GPS is a noisy factor, not an identity |
| Applies to us | (1) Identity association in orchards is mainly **geometric/spatial**, not appearance; (2) under-canopy GPS is unreliable, so GPS is metadata and at most a coarse prior; (3) RealSense-class sensors give usable trunk point clouds at short range |
| Does not apply | Orchard rows are regular and the robot moves continuously (tracking), whereas a handheld returns months later from a different spot in irregular forest |
| **Decision** | GPS is stored with each observation, but identity never depends on it. A spatial prior is left for future work once real field GPS error under hemlock canopy is measured. Depth goes through a `DepthProvider` abstraction (RGB-D / phone / stereo / simulated). |

## 4. OrchardTemporal (CVPR 2026 Workshops)

*Nguyen, Dethlefs, Liu. "OrchardTemporal: A Benchmark for Evaluating
Vision-Language Models on Temporal Reasoning in Apple Orchards", CVPRW 2026,
pp. 9807–9813.*

| | |
|---|---|
| What they did | Built on AppleGrowthVision (33 Jonagold trees, 18 time points). Task T3: given a query image of a tree and N candidates from a different season, pick the same tree. Evaluated 4 VLMs zero-shot, with attribute-guided prompting and one-shot prompting |
| Results | Best cross-seasonal re-ID accuracy is **60 % against a 50 % random baseline** (GPT-4o macro-F1 0.648 zero-shot). Prompting did not help. Authors hypothesise reliance on colour/texture over persistent structure (branching, trunk shape) |
| Applies to us | General visual recognition ≠ individual re-identification, and seasonal appearance change is severe. The **cross-session** regime must be evaluated separately from same-session |
| Does not apply | It evaluates VLMs, not metric-learned embeddings |
| **Decision** | No VLM in the pipeline. Evaluation regimes are separated (same session vs later session). BarkNet has no repeat sessions, so **the cross-season regime remains untested here**. The capture app records timestamps so the team's own data can fill this gap (see experiments.md, "Open blockers"). |

## 5. WildlifeDatasets / MegaDescriptor (WACV 2024, best paper)

*Čermák, Picek, Adam, Papafitsoros. "WildlifeDatasets: An open-source toolkit
for animal re-identification", WACV 2024.*

| | |
|---|---|
| What they did | Toolkit over 63 public re-ID datasets, with closed-set, open-set, disjoint-set and **time-aware** splits. Compared local descriptors (SIFT, SuperPoint), ArcFace vs Triplet, and EfficientNet-B3 vs Swin-B. Trained MegaDescriptor (Swin-L/384, ArcFace) |
| Results | Metric learning beat local-feature matching on most datasets. **ArcFace was more consistent than Triplet**. In their ablation, Swin-B ≥ EfficientNet-B3 in most cases. MegaDescriptor-L beat CLIP, DINOv2 and ImageNet features zero-shot |
| Conflict with MiewID | MiewID reports EfficientNetV2-M > SwinV2-B by 4.5 % on its data. The two papers compare different CNNs (B3 vs V2-M), different data and protocols. **The literature is inconclusive on CNN vs transformer for re-ID** |
| **Decision** | Keep ArcFace-family as the primary loss. Triplet/SupCon/ArcFace were measured as controlled comparisons: all within seed noise, with SupCon/Triplet weakest on cross-capture and same-phone checks. Resolve the backbone question on *our* data: a zero-shot comparison of five backbones, then a fine-tuned EfficientNetV2-M vs DINOv2-S comparison at equal budget. DINOv2-S won clearly (test mAP 0.54 vs 0.27; cross-capture top-1 0.89 vs 0.15), so it is the one primary backbone. Use their split vocabulary: our test identities are disjoint from training. |

## 6. Bark re-identification

*Robert, Dallaire, Giguère. "Tree bark re-identification using a deep-learning
feature descriptor", arXiv:1912.03221 (2019, rev. 2020), Université Laval
(Giguère's group also produced BarkNet).*

| | |
|---|---|
| What they did | Re-identify the **same bark surface** under strong illumination changes. 2,400 bark images annotated by surface; >2M 64×64 patches to train local descriptors (DeepBark, SqueezeBark) vs SIFT/SURF |
| Results | DeepBark: mAP 87.2 % retrieving 11 relevant images among 7,900; Precision@1 99.8 % |
| Applies to us | Bark *surfaces* carry an individual signature that keypoint matching with geometric verification can find, provided the two photos **overlap** |
| Does not apply | Requires re-photographing the same bark patch. In BarkNet, images of one tree show different bark regions (we measured near-zero RANSAC inliers between them, E-local) |
| **Decision** | Keep a cheap local branch (RootSIFT + RANSAC homography, re-ranking only the top-k global candidates) and fuse it through calibration only if it improves validation results. **Capture protocol consequence:** view 1 is anchored to the tree's north side so repeat visits re-photograph overlapping bark. |

## 6b. DINOv2 (the backbone we ended up with)

*Oquab et al., "DINOv2: Learning Robust Visual Features without Supervision", TMLR 2024 (arXiv:2304.07193). Weights are Apache-2.0 (timm `vit_small_patch14_dinov2.lvd142m`).*

| | |
|---|---|
| What they did | Self-supervised ViT pre-training on 142 M curated images (LVD-142M). Features transfer well to fine-grained and instance-level retrieval without fine-tuning |
| Why it is relevant | Bark re-ID is a texture-level, instance-level task far from ImageNet classes. Self-supervised dense features plausibly carry more instance detail than ImageNet-supervised CNN features, which tend to discard "irrelevant" texture |
| Evidence on our data | Best zero-shot backbone of five (E-backbone). After fine-tuning only its last block, it beat EfficientNetV2-M in the same regime by 2× in test mAP, and was far more robust across capture events and phones (E-ablations) |
| Caveats | ViTs need a fixed input size for a fixed position-embedding grid. We use 322 px = 23×23 patches of 14 px, interpolated once at model creation. WildlifeDatasets found transformers (Swin-B) competitive for animal re-ID. MiewID found the opposite with SwinV2-B. Our result is one more data point on bark, not a general law |
| **Decision** | Primary backbone: DINOv2-S/14 at 322 px. Patch tokens → GeM → BN (MiewID head), sub-center ArcFace. |

## 7. Datasets considered

| Dataset | Source / license | Species | Trees | Images | Individual labels | Conditions | Temporal |
|---|---|---|---|---|---|---|---|
| **BarkNet 1.0** (used) | Zenodo 11508014 (corrected re-upload); **MIT** | 23 NE-American species incl. **Tsuga canadensis (PRU)** | 45 hemlocks (≈1,000 trees total) | 986 hemlock (~23K total) | **Yes** (tree id + DBH) | Bark at 20–60 cm, 4 phones/cameras, Quebec City, 2017 | Date/time per tree, but **one session per tree** |
| **Laval Tree-Bark-Re-Identification** (used) | [GitHub](https://github.com/ulaval-damas/Tree-Bark-Re-Identification) (Google Drive), **MIT** | Red pine, elm | 100 (50 + 50) | 2,400 (12 per bark patch, 2 patches per tree) | **Yes** (tree + patch) | Each patch **re-photographed** at night with lamp and phone moved (LG Q6) | Single night per tree |
| CentralBark (Algorithms 2024) | MDPI article | 25 central-hardwood/Appalachian species | — | >19K | Not for individuals | Varying light/moisture | No |
| BarkVisionAI (Sci. Data 2026) | Nature Sci. Data | multiple | — | — | Species | — | — |
| iNaturalist (taxon 48734) | per-photo CC licenses | Tsuga canadensis | many | many | **No** | Citizen photos | Not per individual |
| AppleGrowthVision / OrchardTemporal | per paper | Apple | 33 + 14 | 9,317 stereo pairs | Yes | Orchard, 18 time points | **Yes** |
| Tree-SLAM orchard data | per paper | Apple, pear | rows | RGB-D sequences | Yes | Orchard | Seasons |

**Decision.** BarkNet is the only openly licensed dataset we found with
individual labels for Eastern hemlock, so all hemlock numbers come from it. The
Laval re-ID set is the only open dataset we found where the *same* tree surface is
genuinely re-photographed under changed conditions. We use it to test and to
train robustness to re-photographing (experiments.md E-recapture). Harvard
Forest (tagged hemlocks, crown-health ratings, no tree photos), PhenoCam (canopy
time-lapse) and iNaturalist (no individual identity) were checked and do not provide
individual-hemlock repeat photographs. It
cannot test cross-season re-ID, canopy/branching views, or depth. The capture
app and database are therefore built as the team's data-collection pipeline:
every observation keeps its original JPEGs, per-view metadata, compass heading,
GPS, timestamp, and the tree ID it was assigned.

## 8. Depth sensing for a handheld

| Option | Notes (sources: vendor specs; Tree-SLAM; our simulation) |
|---|---|
| Stereo RGB-D (RealSense D4xx, OAK-D) | Ideal 0.3–3 m (D435: <2 % error at 2 m). Error grows ~quadratically with distance. D435**f** variants add an IR-pass filter for sunlight. USB, works with a Pi 5 |
| Phone LiDAR/ToF (iPhone Pro, some Android) | Dense metric depth at ~0.3–5 m via ARKit/ARCore, but only through a native app. A browser cannot read it |
| Low-cost ToF (e.g. Arducam ToF for Pi) | Low resolution, short range, sensitive to sunlight |
| Passive stereo (two Pi cameras) | Cheap; texture-dependent (bark helps); needs calibration |

**Decision.** `DepthProvider` with RGB-D, phone, stereo and simulated
implementations behind one interface. Depth is used outside the neural network,
for structural consistency (DBH / stem profile) at the candidate level. On real
hemlock DBHs, a DBH gate is worthwhile if the device measures DBH to about 1–2 cm
(E-depth). No consumer device has been measured on real trunks yet, so the
structural signal stays **off by default** until it is calibrated on real field
data.

## 9. Other choices and their sources

* **GeM vs average pooling.** GeM is standard in instance retrieval (Radenović et al., TPAMI 2018) and MiewID uses it. We keep it (learnable p).
* **Embedding dimension.** MiewID uses the backbone width without projection, and we keep that rule. With DINOv2-S the embedding is 384-d (0.75 KB per observation in fp16), vs 2152-d (4.3 KB) for EfficientNetV2-M.
* **Open-set thresholds.** Thresholds are chosen on identity-disjoint validation data at a target false-match rate (default 1 %), because merging two trees' histories is the costliest error. A false "new tree" creates a duplicate that `merge_trees` can repair. This follows the open-set / disjoint split practice in WildlifeDatasets.
* **Multi-view aggregation.** Start with the mean of L2-normalised views (no parameters). Attention pooling and a small transformer are tested in a controlled ablation and kept only if they help (E-aggregation).
