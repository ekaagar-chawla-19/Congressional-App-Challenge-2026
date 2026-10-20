# Production model vs the RTX 3060 BarkNet checkpoints

Compared on the same photos and under the same rules, on CPU, on 2026-10-20:

- **Ours:** the model the app ships, `models/production/hemlock.onnx` (sha256 `fed2aa87…`).
- **f448:** the friend's ViT-S 448 px checkpoint, `vits_448_best.pt` (sha256 `5dfff6e5…`).
- **f224:** the friend's ViT-S 224 px checkpoint, `vits_224_best.pt` (sha256 `d809be24…`).

Both friend checkpoints are from the `barknet-rtx3060` release. They were loaded read-only in eval mode and never modified; their hashes match the release.

## His model is run the way he ran it

His code repo (`ekaagar-chawla-19/CAC`) is not accessible, so his model was rebuilt from the config saved in the checkpoint. The checkpoint loads with strict key matching. On his own protocol, the rebuild reproduces his reported numbers:

- **Protocol:** all 45 hemlocks; 10 trees left out as never-enrolled; each known tree's photo sequence split into a first half (gallery) and a second half (queries).

| | mAP | Top-1, 1 photo |
|---|---:|---:|
| f448, reported | 0.507 | 68.7% |
| f448, here | 0.496 | 68.8% |
| f224, reported | 0.431 | 59.0% |
| f224, here | 0.455 | 63.3% |

Splitting each tree's photos at random instead of into first and second halves inflates the numbers: mAP rises to 0.58 and top-1 to 90%. Neighbouring photos are near-duplicates, so every test below uses the first-half/second-half split.

## Fair test: the 14 hemlock trees no model trained on

These are our split's test trees. Our model never trained on them, and his never saw any hemlock in training. Each figure is averaged over 20 random choices of 4 never-enrolled trees.

| | mAP | Top-1 @1/3/5 photos | New-tree AUROC @1/3/5 |
|---|---:|---|---|
| **Ours** | **0.596** | **75.7 / 83.2 / 84.2%** | **0.80 / 0.82 / 0.82** |
| f448 | 0.578 | 69.4 / 79.5 / 80.6% | 0.71 / 0.78 / 0.81 |
| f224 | 0.541 | 64.4 / 76.0 / 79.9% | 0.65 / 0.68 / 0.65 |

The results on all 45 trees are in `report_reid.json`. Our model trained on 31 of those trees, so its 45-tree numbers are optimistic and are not used for the comparison.

## Decisions with each model's shipped threshold (3-photo scans)

| | Right tree confirmed | Wrong tree confirmed | Never-enrolled tree "matched" |
|---|---:|---:|---:|
| Ours (calibrated fuser, threshold 0.927) | 7% | 0% | 0% |
| f448 (cosine threshold 0.820) | 72% | 16% | 61% |
| f224 (cosine threshold 0.786) | 64% | 17% | 62% |

- **His threshold makes up matches.** About 1 in 6 scans is confirmed as the wrong tree, and most trees that were never enrolled are matched to some enrolled tree.
- **Our threshold is far too strict for hemlocks.** It was fitted on validation trees of all species. It never confirms a wrong tree, but it calls most real revisits "new tree".

## Same rule for every model, threshold set on held-out trees

- **Rule:** a 3-photo scan against 3-photo enrolments, nearest tree by cosine.
- **Threshold:** set on the 9 hemlock validation trees, which no model trained on, for a target false-match rate on never-enrolled trees.
- **Test:** the threshold is then applied unchanged to the 14 test trees.

| Target false matches | Model | Right | Wrong tree | Never-enrolled matched (actual) |
|---|---|---:|---:|---:|
| 1% | Ours | 27.7% | 3.1% | 4.4% |
| 1% | f448 | 38.3% | 6.3% | 12.8% |
| 5% | Ours | 44.1% | 7.9% | 13.4% |
| 5% | f448 | 49.1% | 12.0% | 27.6% |

- **At about the same actual false-match rate, ours confirms more revisits.** Compare ours at the 5% target with f448 at the 1% target: both produce about 13% false matches, and ours confirms 44% of revisits against 38%.
- **Our threshold carries over to new trees more reliably.** Aiming for 1% false matches gives 4% for ours and 13% for f448.

## Fake-match probes (gallery: all 45 hemlocks)

| Probe set | Ours | f448 | f224 |
|---|---:|---:|---:|
| 33 black, white, gray, noise and non-bark images matched to a tree | 0 | 0 | 0 |
| 240 photos of non-hemlock bark (6 species) matched to a hemlock | 0% | 0% | 0% |
| Highest similarity of non-hemlock bark to any hemlock | 0.62 | 0.66 | 0.66 |

- **Neither model invented matches for junk or other species.** Ours also rejects these before matching, at the photo-quality check and the species check (0 of 240 other-species photos passed). The friend's models have no species check, but no other-species photo cleared their thresholds.
- **The earlier "95% match on a black photo" was not the model.** It came from the app's offline demo, which made up scores; that was removed in c9ce3ac.

## Deployability

| | Ours | f448 |
|---|---|---|
| Runs in the app now | Yes | Needs an ONNX export (verified: max difference 3e-7 vs PyTorch, 89 MB) |
| Species check (hemlock or not) | Yes | No |
| Photo-quality check | Yes (server) | No (would reuse ours) |
| Thresholds calibrated on held-out hemlocks | Too strict, needs refitting | Shipped threshold confirms the wrong tree in 16% of scans |
| CPU time per photo, including decode | 0.5 s | 1.3 s (five 448 px crops) |

## Verdict

- **Best results:** ours. It picks the right tree more often and separates new trees from enrolled ones better on hemlocks no model trained on.
- **Most deployable:** ours. It is already integrated and is the only one with species and quality checks.
- **Its weak point is the match threshold.** As shipped it is too strict and calls most revisits "new tree". Refitting it on the 9 hemlock validation trees, with no retraining, is the fix.
- **Swapping in f448 would make the app worse.** Its shipped threshold confirms the wrong tree in about 1 of 6 scans and "recognises" most trees it has never seen.

**Caveat:** 14 test trees, all photographed in one season. Differences of a few points are within noise, and no model has been tested on revisits months apart.

Reproduce with the scripts in `scripts/`: `embed.py`, then `eval.py`, `fair.py` and `probes.py`.
