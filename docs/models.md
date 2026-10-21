# Two re-ID models: delta and gamma

The app asks which model to use before every scan (a small sheet, like the model menu in ChatGPT or Claude).
Both models run for real on the HemlockID server (`hemlock-api`); the phone only chooses.

| | Model Delta | Model Gamma |
|---|---|---|
| What it is | Our production model, `models/production/hemlock.onnx` | The RTX 3060 BarkNet checkpoint `vits_448_best.pt`, exported unchanged to `models/gamma/gamma.onnx` |
| Network | DINOv2 ViT-S/14 at 322 px, 384-d embedding, species head | DINOv2 ViT-S/14 at 448 px, CLS+mean pooling, 256-d embedding, no species head |
| Per photo | one 322 px centre crop | short side 640, five 448 px crops, mean of the crop embeddings |
| Species check | yes: only Eastern hemlocks get a tree ID | none: the tree is assumed to be a hemlock; results say "species not checked" |
| CPU time per photo (4-core laptop) | 0.2 s | 2.4 to 2.7 s |
| Right tree first, 2,371 real iNaturalist hemlocks (one photo, about 1,100 other trees in the forest) | 35% | 53% |
| Real hemlock photos accepted by its species check | 14% | (no check) |

The numbers come from `docs/results/model_comparison/README.md`. In short: gamma recognises trees better on real
phone photos; delta is faster and checks the species, but its species check turns away most real (non-BarkNet)
hemlock photos.

## Run

```bash
hemlock-api            # loads both models: "re-ID models: delta=..., gamma=..."
hemlock-api --no-gamma # delta only
hemlock-api --demo     # two mock models, no weights (results are meaningless)
```

API: `GET /api/v1/models` lists them; choose with `POST /api/v1/captures {"model": "gamma"}`, the `model` form
field of `POST /api/v1/identify`, or the `X-Model` header. Every result says which model produced it (`model`,
`model_name`) and whether the species was checked (`species_checked`).

## How one forest works with two models

Each model has its own embedding space, so every visit is fingerprinted by **every** model
(`model_embeddings` table, one row per visit and model):

* the scan's own model stores its fingerprint when the visit is saved;
* the other model embeds the visit's stored photos in the background straight after, and before any identify it
  catches up on anything still missing (so a tree registered with gamma is recognised by delta and the other way
  round; checked in `tests/end_to_end/test_two_models_real.py`, where the background fingerprints equal the
  direct ones to cosine > 0.999);
* at start-up the server queues the catch-up for every forest (trees stored before gamma existed);
* databases from before this change keep working: their stored embeddings are adopted as delta's.

Health data (checklist, ESP32 readings, notes, severity) belongs to the visit, not to a model, so the disease
diagnosis is the same whichever model identified the tree.

## Gamma's weights are frozen; its thresholds are calibrated post hoc

`scripts/export_gamma.py` checks the checkpoint's sha256 against the GitHub release, rebuilds the network from
the config saved in the checkpoint, loads it with strict key matching and exports it (ONNX output equals
PyTorch within 3e-7). Nothing is trained. `models/gamma/gamma.json` records the source digest and
`"weights_modified": false`.

The app's decision logic needs thresholds the checkpoint never had (fused P(same tree), view checks,
duplicate-photo checks). `scripts/calibrate_gamma.py` fits them with the app's own code (EmbeddingIndex,
candidate_features, LogisticCalibrator, decide) on hemlocks kept apart from the ones it reports:

* fit: 31 BarkNet hemlocks outside our test split + iNaturalist trees with an even observation id;
* report (held out): the 14 BarkNet test hemlocks + iNaturalist trees with an odd id.

Held-out results (`models/gamma/calibration.json` → `provenance.held_out_decisions`):

| | right tree confirmed | wrong tree confirmed | never-enrolled tree matched |
|---|---:|---:|---:|
| iNaturalist, full forest | 23% | 0% | 0% |
| iNaturalist, new forest with 1 tree | 43% | 0% | 0% |
| BarkNet test stand (one stand, trees look alike) | 33% | 0.8% | 11% |

Two fixes came from testing with the real model:

* **gap_floor**: in a forest with one tree, the "gap to the next-best tree" feature used to equal the score
  itself, and gamma (whose different hemlocks already score 0.7-0.8) confirmed every new hemlock as that tree at
  ~100%. A virtual competing tree at the median best-other score (0.61) fixes it; delta's calibration has no
  floor, so delta is unchanged.
* **duplicate photos**: gamma scores neighbouring views of a trunk close to a re-shoot, so the hard "same photo"
  limit comes from all 639 neighbouring photo pairs (99.7th percentile, 0.970), not a 30-pair sample (which
  rejected 1 genuine photo in 27).

## Upgrading an existing data folder

Checked with yesterday's code: a data folder made before this change (demo account + a tree registered by delta)
starts with today's server; at start-up every stored visit gets a gamma fingerprint from its stored photos and
every demo placeholder a gamma placeholder (187 of 187), and gamma then recognises the stored tree from other photos taken with the same phone (score 0.85 against at most 0.15 for any other tree). In that run delta's species check turned the same photos away as not a hemlock, its known weakness.

## Limitations

* Gamma has no species check. Use **Hemlock check** (delta's species head) when unsure; note that delta's
  species check itself rejects most real phone photos of hemlocks (it was trained on BarkNet only).
* Gamma is 10x slower per photo on a CPU (five 448 px crops); a 3-photo scan adds about 7 s of server time.
* The first gamma scan in a forest with many trees registered before gamma was added waits for their
  fingerprints if the start-up catch-up has not finished (about 2.5 s per stored photo).
* **Revisits with a different phone are rarely confirmed automatically.** On the 3 BarkNet hemlocks photographed
  by two phones, gamma ranks the right tree first but its similarity drops to about 0.57, below what different
  look-alike hemlocks in one stand score, so at the 1% false-match target it answers "new tree" (0 of 120 cross-phone
  revisits confirmed, 0 wrong); lowering the gap floor does not change this (checked at the 10th, 25th and 50th
  percentile). Delta behaves the same way. The right tree is still listed first under **Other matches**, where
  one tap assigns it. Fixing this needs field photos of the same trees from different phones and days.
* Same-day photos only: no model has been tested on revisits months apart.
* Phone-side Bluetooth reading of the ESP32 needs Web Bluetooth (Chrome on Android or a desktop). On iPhone
  Safari or Expo Go, paste the node's JSON line or type the numbers; both feed the same diagnosis.
