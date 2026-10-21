# Guided scanning, the matching explainer and the tree's digital twin

## AI-guided active scanning

After every photo, the server ranks the registered trees using the photos taken so far. It uses the same
retrieval, fusion and calibrated thresholds as the final decision (`HemlockSentinel.preview`).
`pipeline/guidance.py` then turns that ranking into one short instruction. The app shows it as a single card
over the camera: a title, one line of detail, and the two leading trees.

| State | When | What it asks for |
| --- | --- | --- |
| `retake` | the last photo failed the quality check | the same view again, with the reason |
| `species_doubt` | Model Delta's species head reads "not hemlock" on 2+ photos | move closer to the trunk |
| `first_tree` | the forest has no trees yet | the standard 3 views, then register |
| `confident` | one tree clears the calibrated match line, the runner-up is far behind | the rest of the 3 views, then Identify |
| `ambiguous` | two trees are close | a lower-trunk close-up, then the extra views |
| `contradicting` | the photos point at different trees | stay on one trunk |
| `likely_new` | nothing is close | Identify registers a new tree |
| `building` | evidence still weak | one more view, up to 6 trunk photos |

The policy is rule-based on purpose: every request has a reason the user can see. The next view asked for
depends on that reason and on what was already taken, not on a fixed script. After 6 trunk photos it stops
asking, and an unresolved scan is saved as uncertain for review.

The **Hemlock check** (home screen) now takes several photos and lists each photo's hemlock probability.
It uses Model Delta's species head; Model Gamma has none.

## "How HemlockID thinks"

`mobile/src/app/fingerprint.tsx` has three story-style steps: fingerprint, matching and decision. Tap
the right side or Next to go on, and the left side to go back. A segmented bar fills one cell per step.
The art is drawn (seeded procedural bark in `FingerprintArt.tsx`), not real data, and is labelled
"Illustration". You can open it from the scan result ("How did it match?"), Settings and About.

## Digital twin (tree page)

`GET /trees/{id}` now also returns (`api/twin.py`):

* `sensor_history`: every visit with an ESP32 reading, newest first, with VPD from temperature and humidity.
  The app shows the latest 3 and a "See all" button.
* `environment`: the latest reading in one sentence ("Low water stress: moist soil, mild air."). It also
  lists the changes since the previous reading: soil ±5 points, VPD ±0.3 kPa, temperature ±3 °C. Smaller
  moves are treated as noise.
* `since_last_visit`: severity and per-condition likelihood changes, and new signs. These compare the last
  two visits that recorded health or sensor data, so a photo-only rescan does not read as "no change".
* `next_action`: one line, picked by fixed rules. Likely HWA comes first, then likely EHS, unchecked twigs,
  water stress, a missing ESP32 reading or crown rating, and finally a routine re-scan.

Sections and forests average each tree's *latest* reading (`analysis.summarize`), so a tree with many visits
does not count more than one with a single visit.

## Forests

The forest list has a **New forest** button (name, optionally centered where you stand). It works on
the server (`POST /forests`) and in the offline demo (local database).
