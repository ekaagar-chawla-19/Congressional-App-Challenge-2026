# Architecture

Hemlock Sentinel answers two questions about a tree photographed with the
handheld:

1. *What species is this, and is it supported?* (species gate)
2. *Is this the same physical tree as one already in the database, and which one?* (individual re-identification)

Experimental results that justify each choice are in
[`experiments.md`](experiments.md), and the literature in
[`research/literature_review.md`](research/literature_review.md).

```
   GUIDED CAPTURE (3 required trunk views + 2 optional: branching, canopy)
   per view: decode once → quality checks → face blur → network input
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
     DINOv2-S/14 (shared, 1 pass/view)         RootSIFT keypoints (trunk views,
          │                                        off by default — E-local)
          │                                       │
          patch tokens → GeM (learned p) → BN     │        depth frame (optional)
          │                                       │              │
     384-d embedding ──► species head (Linear on L2-normed embedding)
          │                     │                 │              │
          │        species gate (validated threshold)            │
          │                     │                 │              │
   quality-weighted mean of L2-normalised identity views         │
          │                                       │              │
   cosine vs gallery (max over each tree's observations)         │
          │                                       │              │
     top-k candidates ──► features: global, gap, view agreement, local, structure
                                   │
                  logistic calibrator → P(same tree)  (fitted on validation)
                                   │
          ┌────────────────────────┼────────────────────────────┐
          ▼                        ▼                            ▼
   existing tree H-017     uncertain (contradicting      new tree H-158
   (P ≥ threshold, views    or mixed views → take        (no candidate passes)
    consistent)             another view / user decides)
                                   │
         SQLite: trees, observations (timestamp, GPS, env), views (image key,
         fp16 embedding, quality, local features, depth); blobs content-addressed
```

## 1. Guided capture (`acquisition/protocol.py`, `app/static/index.html`)

The user is walked through standard views: (1) trunk bark from the tree's
**north** side at chest height, (2) a quarter-turn clockwise, (3) another
quarter-turn, then optionally (4) branching structure and (5) canopy. A green
ring around the viewfinder and dots ●●●○○ show progress. The browser records
the compass heading when the device reports it.

Viewpoint consistency is deliberate. Local bark matching only works when two
captures overlap: different bark regions of the same BarkNet tree gave the same
inlier counts as different trees (E-local). Anchoring view 1 to north makes
repeat visits photograph overlapping bark.

Views 4–5 are **stored but not used for identity**. The current model was
trained and validated only on bark, so feeding canopy photos into the identity
embedding would be an unvalidated change. They are collected for future
training and for the planned health work.

## 2. Quality checks (`acquisition/quality.py`)

Cheap per-view checks with a message the user can act on:

* blur (Laplacian variance)
* exposure (mean luminance, clipped fraction)
* "no tree structure" (edge density)
* **compass**: consecutive rotation views must differ by ≥ 30° of heading
* duplicate view (embedding cosine to an earlier view): reject above 0.97, warn above the calibrated 0.886

On bark, re-shoots and genuine next views overlap in embedding similarity
(E-duplicate), so the compass does the reliable part.

Blur and texture thresholds were derived from real BarkNet images against
blurred copies (E-quality). Sharpness also sets a soft weight for multi-view
aggregation.

## 3. Privacy (`acquisition/privacy.py`)

Faces are detected with OpenCV's YuNet (227 KB, MIT) and blurred **before
anything is stored**. Original bytes are stored only when no face was found. No
user identity is attached to observations. If the detector is missing, views
are tagged `faces_blurred = -1` so unscreened images can be found later.

**Decoding.** Each JPEG is decoded once, directly at reduced scale (libjpeg DCT
scaling to short side ≥ 640 px). That is the same scale the training cache used,
so there is no train/serve skew, and it is 2× faster and lighter for 12 MP
photos (E-deploy, E-efficiency).

## 4. Shared backbone: DINOv2-S/14 → GeM → BatchNorm (`reid/`)

* **Backbone: DINOv2-S/14** (`timm vit_small_patch14_dinov2.lvd142m`, self-supervised LVD-142M weights, Apache-2.0, 22 M params) at 322 px, i.e. 23×23 patch tokens.
  * **How it was chosen.** The project started from MiewID's EfficientNetV2-M as the literature baseline. Controlled experiments then replaced it (E-backbone, E-ablations). At equal training budget, DINOv2-S roughly doubled test mAP on unseen hemlocks. It was also far more robust to different capture events and to impostors photographed with the same phone. And it is 2.4× smaller.
  * **Only one backbone ships.** EfficientNetV2-M remains selectable in code only to reproduce the comparison.
* **GeM pooling** over the patch-token grid (generalised mean, p learned, init 3). This is MiewID's choice and standard for instance retrieval. Patch tokens are pooled rather than the CLS token, so local bark texture contributes everywhere.
* **BatchNorm1d** on the pooled 384-d vector. Its output is the embedding. As in MiewID there is no projection layer; L2 normalisation happens at retrieval time.
* **Species head.** One `Linear(384 → n_species)` on the L2-normalised embedding. One forward pass per view gives both species and identity, with no second network on the device.

**Training** (`training/reid/train_tail.py`): sub-center ArcFace (k=3) with
MiewID's dynamic margins in [0.2, 0.5], s=30. The model is selected on hemlock
*validation* mAP.

On this project's CPU-only budget, the first 8 of 12 transformer blocks are
frozen and their outputs cached with 4 augmentations per training image. The
last 4 blocks, final norm, GeM and BN are fine-tuned. With a GPU the same code
can fine-tune end to end.

Losses (ArcFace, SupCon, Triplet) and multispecies vs hemlock-only identities
were compared in controlled runs. None beat sub-center ArcFace beyond seed noise
(E-ablations).

## 5. Species gate (`species/`)

Per-view softmax probabilities are averaged over the identity views. If the top
probability is below the **validated threshold**, the result is "Unknown —
retake photos / species not supported" and no ID is produced. The threshold
maximises balanced accuracy between accepting correctly classified known species
and rejecting a held-out species (Thuja) on validation. It is then tested on a
different never-seen species (Picea rubens).

A known but non-hemlock species is named but gets no individual ID.
`REID_SUPPORTED` and `ID_PREFIX` in `species/labels.py` are the switches for
adding species later.

## 6. Multi-view aggregation (`reid/multiview.py`)

The tree embedding is the quality-weighted mean of the L2-normalised identity-view
embeddings, re-normalised. It has no parameters and is order-invariant.
Attention pooling and a 2-layer transformer were evaluated (E-aggregation) and
are not used in production unless they beat the mean.

## 7. Global matching (`reid/retrieval.py`)

Exact cosine search over every stored observation embedding. A tree's score is
the **max over its observations**, so a tree photographed in several seasons
matches a query from any of them. Search is a single BLAS matrix product and
`reduceat` (sub-ms for 100 trees; see E-efficiency). No approximate index is
needed at site scale.

## 8. Local and structural matching (`reid/local_matching.py`)

* **Bark keypoints.** RootSIFT (500 keypoints at 640 px) + ratio test + RANSAC homography, run only against the top-k global candidates. Descriptors are cached as uint8 npz (~54 KB/view). **Off by default:** it added nothing over the fine-tuned global embedding on BarkNet (E-local).
* **Trunk structure from depth.** Back-projects the depth map, isolates the trunk, fits circles per 10 cm slice to get a stem diameter profile, and compares two profiles within a tolerance while searching a vertical offset (after Yrttimaa et al.'s TLS stem-profile fingerprints).

Each signal enters the decision only through a calibrated fuser fitted on data
where it is available (section 9). Structure is off until it is calibrated on
real field depth.

## 9. Decision (`reid/fusion.py`, `reid/calibration.py`)

For each of the top-k candidates: `global`, `gap` (vs best other tree),
`agreement` (fraction of views whose own top-1 is this tree), and optionally
`local` and `structure`. A logistic calibrator fitted on validation pairs gives
P(same tree). The decision then works like this:

* `P_best < match_threshold` → **new tree**. Exception: if a single view on its own matches some tree above the per-view threshold, the capture is mixed, so the result is **uncertain** rather than silently creating a tree.
* `P_best ≥ threshold` but some view's own top-1 is a different tree by more than the calibrated margin → **uncertain**: the app asks for another view. At the last view it stores the observation unassigned and lets the user choose.
* Otherwise → **existing tree**.

All thresholds (`match_threshold`, `global_threshold`, `view_match_threshold`,
`view_contradiction_margin`, `species_threshold`) are fitted on validation data
at a target false-match rate (default 1 %) by `scripts/calibrate.py`, and saved
with their provenance. The highest similarity is never accepted blindly.

## 10. Persistence (`database/`)

SQLite (WAL) with three tables:

* `trees(tree_id, species, created_at, last_seen_at, observation_count, canonical_embedding, merged_into)`
* `observations(observation_id, tree_id, timestamp, GPS, species, confidence, decision, match_probability, aggregated_embedding, model_version, environment, metadata)`
* `views(observation_id, view_index, view_type, image_key, depth_key, local_features_key, embedding, quality, heading)`

Design rules:

* **IDs**: `H-001`, `H-002`, … are allocated from a per-prefix counter inside a write transaction. They are never derived from row positions and are never reused, even after `merge_trees`.
* **Blobs** (JPEG, depth, keypoints) are content-addressed (sha256) files, so identical bytes are stored once. The DB holds only keys. Original JPEG bytes are kept without re-encoding.
* **Embeddings** are float16 BLOBs: 4.3 KB per view or observation.
* **Longitudinal history**: observations per tree, ordered by timestamp (`get_observations`). Unresolved observations are stored with `tree_id = NULL` and can be attached later (`assign_observation`). Duplicates can be merged.

## 11. Hardware abstraction (`acquisition/interfaces.py`)

| Interface | Implementations | Notes |
|---|---|---|
| `Camera` | browser upload (phone), `FileCamera`, `ArrayCamera`; Picamera2 adapter on the Pi | |
| `DepthProvider` | RGB-D, phone, stereo, `SimulatedDepth`, `NoDepth` | `DepthFrame` carries intrinsics and a noise model |
| `GPS` | `FixedGPS`, `NoGPS` | |
| `EnvironmentalSensors` | `NullSensors` | |
| `Storage` | `LocalFileStorage` | |
| `ModelRuntime` | `OnnxRuntime` (edge default), `TorchRuntime`, `MockRuntime` (tests) | |

The pipeline only sees these protocols, so a phone, a Pi with a RealSense, or a
test dataset all run the same code.

## 12. What was deliberately *not* built

* No multi-view transformer in production unless it is measured to help.
* No depth inside the CNN.
* No VLM.
* No microservices or cloud dependency: one process, SQLite, and files.
* No ensemble.
* No tree-health model: the re-ID pipeline has to be validated on real repeat visits first.
