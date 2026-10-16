# Hemlock Sentinel API (backend for the mobile app and the Raspberry Pi)

The phone app (React Native / Expo) or the Raspberry Pi takes the photos. This
backend runs the trained model and keeps each account's forests and trees:

```
 phone (React Native) ── Wi-Fi/HTTP ──┐
                                      ▼
 Raspberry Pi + camera ─ Bluetooth ─▶ hemlock-bt-receiver ─▶ hemlock-api (this repo, Python)
                                                              • sign-in, forests (one tree database per forest)
                                                              • quality checks, face blur
                                                              • DINOv2-S model (models/production/hemlock.onnx)
                                                              • species gate → match against the forest's trees
                                                              • existing / new / uncertain, severity ratings
                                                              • forest map (GeoJSON + /map page)
```

Model: production **v2** (`hemlock-dino_plus_recapture-20261007`), 87 MB ONNX, CPU only.
Decision thresholds: `models/production/calibration.json` (fitted on validation trees).

**Severity is not predicted by the model.** The model identifies species and
individual trees. Severity (0 none, 1 light, 2 moderate, 3 severe, e.g. hemlock
woolly adelgid infestation) is the observer's rating, sent with the photos or
set later. The map shows each tree's most recent rating.

## Run it

**Option A: Python** (Python 3.10+)

```bash
git clone -b backend/api https://github.com/ekaagar-chawla-19/Congressional-App-Challenge-2026
cd Congressional-App-Challenge-2026
python -m pip install -e ".[onnx,app]"
hemlock-api            # → http://localhost:8000/map  (sign in: demo@hemlock.test / hemlock-demo)
                       #   http://localhost:8000/docs (try every endpoint)
```

**Option B: Docker**

```bash
docker build -t hemlock-api .
docker run -p 8000:8000 -v hemlock-data:/data hemlock-api
```

On first start a **demo account** is created (`demo@hemlock.test` / `hemlock-demo`,
skip with `--no-demo-account`) with two North Georgia demo forests full of
**placeholder** hemlocks (positions, visit dates and severity ratings, no photos)
so the account overview and map have something to show. Photos you capture
while signed in as the demo user are real and stored normally.

![Forest map](images/forest_map.png)

`/map` is a demo page to show the backend working (sign in → pick a forest →
every hemlock colored by severity; click one for its history and photo). The
real app UI is the React Native frontend.

In `/docs`: call `POST /api/v1/auth/login`, copy the `token`, click **Authorize**
(top right) and paste it; then fill `x-forest-id` (the forest number from
`GET /api/v1/forests`) on tree, capture and identify calls. The TypeScript client
does all of this for you.

Settings (flags or environment variables):

| Flag | Env | Default |
|---|---|---|
| `--data` | `HEMLOCK_DATA` | `runs/api` (accounts + one folder per forest) |
| `--no-demo-account` | | demo account is created |
| `--single` | | off: accounts + forests. On: one shared database, no sign-in (`--db`, `--blobs`) |
| `--model` / `--calibration` | `HEMLOCK_MODEL` / `HEMLOCK_CALIBRATION` | `models/production/…` |
| `--port` | `PORT` | `8000` |
| `--cors` | `HEMLOCK_CORS` | `*` |
| `--demo` | | off (mock model, results meaningless; for UI work without the model) |
| | `HEMLOCK_API_KEY` | unset; set = every `/api/v1/*` call except `/health` also needs `X-API-Key` |

### Sign-in and forests

```
POST /auth/register {email, password (8+), name}   → {token, user}
POST /auth/login    {email, password}               → {token, user}
then on every call:  Authorization: Bearer <token>
GET  /me             → the whole account: every forest with tree count, visits, severity breakdown
POST /forests        {name, lat?, lon?}
then on tree / capture / identify / map calls:  X-Forest-Id: <forest_id>
```

Each forest is a separate tree database: IDs (`H-001`, …) are per forest, and a
capture is only matched against trees of the forest it is sent to. Nobody can
read or write another account's forests (tested). This is demo-grade sign-in
(scrypt-hashed passwords, 30-day tokens): add HTTPS, rate limiting and password
reset before real deployment.

### Reaching it from a phone

The phone and the computer running the backend must be on the same Wi-Fi.
Use the computer's LAN address, e.g. `http://192.168.1.20:8000` (find it with
`ipconfig` on Windows, `ipconfig getifaddr en0` on macOS). Plain `http://`
works in Expo Go during development. A release build needs HTTPS (iOS) or
`usesCleartextTraffic` (Android). For testing away from home Wi-Fi, a tunnel
such as `ngrok http 8000` gives an HTTPS URL.

## Raspberry Pi → model over Bluetooth

The Pi only takes photos; the model runs on the computer with the backend.
Photos travel over Bluetooth Classic (RFCOMM, a wireless serial link; ~2 MB per
3-photo capture takes several seconds) and the identification comes back to the
Pi over the same link.

```
Pi:  hemlock-bt-send  ── photos ──▶  computer: hemlock-bt-receiver ──HTTP──▶ hemlock-api
     prints "Existing tree H-017"  ◀── result ──┘
```

**Computer (Linux with Bluetooth, e.g. a laptop or a second Pi):**

```bash
hemlock-api &
bluetoothctl   # then: power on, discoverable on, pairable on   (pair once with the Pi)
hemlock-bt-receiver --email demo@hemlock.test --password hemlock-demo --forest 1
# prints: waiting for the Pi on Bluetooth RFCOMM channel 1
```

**Raspberry Pi (Raspberry Pi OS):**

```bash
bluetoothctl   # then: scan on, pair <MAC of the computer>, trust <MAC>
git clone -b backend/api https://github.com/ekaagar-chawla-19/Congressional-App-Challenge-2026
cd Congressional-App-Challenge-2026
export PYTHONPATH=src            # the sender needs only the Python standard library
python3 -m hemlock_sentinel.bluetooth.pi_sender --address <MAC> --ping
python3 -m hemlock_sentinel.bluetooth.pi_sender --address <MAC> --camera 3 --lat 34.83 --lon -85.48 --severity 1
#   [1/3] Stand 1 m from the tree, NORTH side of the trunk... Press Enter
#   ...
#   Eastern hemlock (98%)
#   Existing tree H-017 (p=0.99)
python3 -m hemlock_sentinel.bluetooth.pi_sender --address <MAC> photo1.jpg photo2.jpg photo3.jpg   # from files
```

`--camera` uses the Pi camera through `picamera2` (preinstalled on Raspberry Pi
OS). If the computer has no Bluetooth or is not Linux (macOS Python has no
RFCOMM sockets), run the same link over Wi-Fi: `hemlock-bt-receiver --tcp 9000`
on the computer and `--tcp <computer-ip>:9000` on the Pi.

What has been tested: the wire format, and the whole path Pi sender → receiver
→ backend → model → result back to the Pi, over TCP with the real model (a
held-out hemlock registered as new, then recognised from different photos at
p = 0.99). **Not yet tested on real Bluetooth hardware**: the RFCOMM socket
code is the standard Linux API, but pairing and throughput need a check on the
actual Pi.

## TypeScript client (for the React Native app)

`client/` is a dependency-free TypeScript client whose types are generated from
this server's OpenAPI spec, so the app and backend cannot silently disagree.

```bash
cd client && npm install && npm run build
# in the app:  npm install ../path/to/client
```

```ts
import { HemlockClient, HemlockApiError } from "@hemlock-sentinel/client";

const api = new HemlockClient({ baseUrl: "http://192.168.1.20:8000" });
await api.login(email, password);              // keeps the token (persist it with expo-secure-store)
const account = await api.me();                // forests, tree counts, severity breakdown
api.setForest(account.forests[0].forest_id);

// three trunk photos (north side first, then quarter-turns clockwise) + the observer's severity rating
const r = await api.identify(
  [{ uri: north.uri }, { uri: right.uri }, { uri: right2.uri }],   // expo-camera / image-picker results
  { location: { lat, lon, accuracy_m }, severity: 2, healthNotes: "wool on lower branches" },
);
switch (r.action) {
  case "done":   show(`${r.species?.name}: ${r.tree_id}`, r.probability); break;      // existing or new
  case "review": pickFrom(r.candidates, (treeId) => api.assignObservation(r.observation_id!, treeId)); break;
  case "retake": showProblems(r.views.filter((v) => !v.accepted)); break;
}

// map: GeoJSON points with severity → react-native-maps <Marker>s
const map = await api.forestMap();
map.features.map((f) => ({ id: f.properties.tree_id, lat: f.geometry.coordinates[1],
                           lon: f.geometry.coordinates[0], severity: f.properties.severity_label }));

<Image source={api.imageSource(tree.thumbnail_url!)} />   // includes sign-in headers
```

Errors throw `HemlockApiError` with `.status`, `.code` (stable, e.g.
`not_signed_in`, `forest_required`, `tree_not_found`, `bad_image`, `network_error`)
and a readable `.message`.

Check the client against a running backend: `npm run test:live -- photo1.jpg … photo6.jpg`
(6 photos of one tree: signs in to the demo account, creates a test forest,
enrols with 3, revisits with the other 3, checks severity and the map).

## The two ways to identify a tree

**One-shot** (`POST /api/v1/identify`): all 3–7 photos in one request.
Simplest. The result is always stored (uncertain ones go to the review queue);
`commit=false` is a dry run.

**Guided** (`/captures`): one photo at a time with instant feedback, which is
what the field protocol needs:

```
POST /captures                         → capture_id, next_view (instructions to show)
POST /captures/{id}/views   (photo)    → view.accepted? problems ("too blurry", "same as view 1: move…"),
                                         next_view, can_identify
   … repeat until can_identify …
POST /captures/{id}/identify           → action:
     "done"                  stored; status "existing" (tree_id) or "new" (new tree_id)
     "capture_another_view"  views disagreed: take next_view, then identify again
     "review"                stored unassigned: user picks from candidates
     "retake"                fewer than 3 good trunk photos
```

Uncertain cases are never merged automatically. Two user actions fix the database:

* `POST /observations/{id}/assign {"tree_id": "H-004"}` (or `"new"`): resolve a
  review item, or correct a wrong automatic match with one tap.
* `POST /trees/{id}/merge {"duplicate_tree_id": "H-009"}`: fold a duplicate tree in.

Retired tree IDs are never reused.

## Endpoints

All under `/api/v1`. **Forest** = needs `X-Forest-Id` (accounts mode).

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness, model version, face blur active (no sign-in) |
| GET | `/model` | model version, species, calibration provenance |
| GET | `/protocol` | the guided photo sequence and its instructions |
| POST | `/auth/register`, `/auth/login` | → token |
| POST | `/auth/logout` | revoke the token |
| GET | `/me` | the account: every forest with tree count, visits, severity breakdown |
| GET / POST | `/forests` | list / create |
| GET | `/forests/{id}` | one forest's summary |
| GET | `/forests/{id}/map` | GeoJSON: every tree with location and latest severity |
| GET | `/map` | same, for the current forest (**forest**) |
| POST | `/captures` | start a guided capture (held in memory 30 min) (**forest**) |
| GET | `/captures/{id}` | capture state |
| POST | `/captures/{id}/views` | add one photo (`image`, optional `view_key`, `heading_deg`) |
| POST | `/captures/{id}/identify` | decide; JSON `{force_commit?, location?, severity?, health_notes?}` |
| DELETE | `/captures/{id}` | cancel |
| POST | `/identify` | one-shot (`images[]`, optional `view_keys`, `headings`, `lat`, `lon`, `accuracy_m`, `severity`, `health_notes`, `commit`) (**forest**) |
| GET | `/trees` | trees with latest severity and location, most recently seen first (**forest**) |
| GET | `/trees/{id}` | a tree and its full history (severity per visit) |
| PATCH | `/trees/{id}` | `{notes}` |
| POST | `/trees/{id}/merge` | `{duplicate_tree_id}` |
| GET | `/observations` | `status` (repeatable), `unassigned`, paging; review queue = `?status=uncertain&unassigned=true` |
| GET | `/observations/{id}` | one observation |
| PUT | `/observations/{id}/health` | `{severity, notes}` |
| POST | `/observations/{id}/assign` | `{tree_id}`: existing ID or `"new"` |
| GET | `/images/{key}` | stored photo (JPEG) (**forest**) |

Full schemas: `/docs` on a running server, or [`docs/api/openapi.json`](api/openapi.json).

All errors have one shape, `{"error": {"code": "...", "message": "..."}}`:
`400` bad input (`bad_image`, `forest_required`, `unknown_view`, `wrong_view_count`, …),
`401` `not_signed_in` / `bad_credentials`, `404` `*_not_found`, `409` `email_taken` /
`forest_exists` / `tree_merged` / `capture_finished`, `413` `image_too_large` (25 MB per photo),
`422` `invalid_request`.

## What the numbers mean (show these honestly in the app)

* `species.confidence`: species gate. Re-identification only runs for Eastern
  hemlock above the validated threshold (test: hemlock precision 1.00, recall 0.97;
  0 of 236 never-seen red spruce photos called hemlock).
* `probability`: calibrated probability that `tree_id` is the right tree. Automatic
  matches require ≥ 0.93 (thresholds set for a 1 % false-match rate on validation trees).
* `candidates`: top 5 trees with scores, for the "is it one of these?" screen.
* `severity`: the observer's rating, not a model output.
* Expect the right tree at the top of the list 87 % of the time for hemlocks on
  BarkNet test trees and 99–100 % for re-photographed bark patches. Different-day
  re-identification of hemlocks has not been measured yet (docs/experiments.md).
  The thresholds come from BarkNet cameras: recalibrate on the team's own field data
  (README, "Collecting the team's own dataset").

## Tests

```bash
pytest tests/integration/test_api_v1.py tests/integration/test_accounts_forests.py \
       tests/integration/test_bluetooth_link.py          # API, accounts, Pi link (mock model, fast)
pytest tests/end_to_end/test_api_real_model.py           # production model on held-out BarkNet trees
python scripts/export_openapi.py && (cd client && npm run gen && npm run typecheck)   # after API changes
```
