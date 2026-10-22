# Project log: everything done since the repo was cloned (Oct 21–22, 2026)

The repo was cloned from `prototypes/hemlock-sentinel`, all branches were combined, and the hardware, app and
backend were integrated end to end. This file lists everything that was done, in order, with how it was checked.
The final state is on branch **`final-integrated`** (same commits as `final`).

For using it: [standalone_and_sensor_unit.md](standalone_and_sensor_unit.md) (summary + offline instructions),
[phone_only.md](phone_only.md) (the app with no computer), [esp32_wifi.md](esp32_wifi.md) (hardware, wiring, battery).

---

## 1. Combined all the branches

* Went through every branch on GitHub: `main`, `final`, `prototypes/hemlock-sentinel`, `backend/api`,
  `mobile-app`, `results/rtx3060-barknet`, `claude/amazing-bell-oypue7`.
* Everything except `results/rtx3060-barknet` was already contained in `main` / `final`.
* The combined branch is `final` plus a merge of `results/rtx3060-barknet`, which adds the RTX 3060 BarkNet run
  artifacts in `docs/results/rtx3060-barknet/`.

## 2. The phone ↔ ESP32 link over the ESP32's own Wi-Fi

The ESP32 is a Wi-Fi access point. The phone joins it and talks plain HTTP/JSON, with no router, internet or
Bluetooth library. This works in Expo Go, in any browser and in the app build.

**Firmware** (`firmware/esp32_wifi_node/`):

* Wi-Fi network `HS-ESP32-xxxx` (named from the chip ID), password `hemlock-sentinel`, address `192.168.4.1`, also
  `hemlock.local`.
* API:

  | Request | Answer |
  |---|---|
  | `GET /api/v1/status` | the unit's state |
  | `GET /api/v1/reading` | the latest reading |
  | `POST /api/v1/measure` | measure now |
  | `GET /api/v1/readings?since=N` | a 6-hour log, paged |

  CORS is open; errors are JSON.
* A reading every 10 s; one logged per minute (last 360 kept). USB serial prints JSON; type `r` to measure now.

**Laptop side** (`src/hemlock_sentinel/esp32/wifi.py`, `bridge.py`):

* A Python client for the unit, and `hemlock-esp32 simulate`, a fake unit with the same API for testing without
  hardware.
* `hemlock-esp32 read|log|visit --wifi` to read the unit, dump its log, or send a reading to the backend as a
  visit.

**App side**: `mobile/src/esp32.ts` (the unit's API client) and `mobile/src/device.ts` (find, connect, pair).
The old Bluetooth / paste UI (`Esp32Readings.tsx`) was removed.

## 3. Sensor firmware on the real board

* **Board:** ESP32-D0WD-V3 (CP2102 USB), `HS-ESP32-1C49`, flashed with `arduino-cli` (esp32 core 3.3.7).
* **Wiring:** kit 3-pin modules through the 37-kit shield, which is fed **3.3 V** (shield 5V ← ESP32 3V3,
  because ESP32 pins aren't 5 V tolerant).

  | Sensor | Shield pin | ESP32 pin |
  |---|---|---|
  | soil probe | A3 | GPIO34 |
  | light (photoresistor) | A2 | GPIO35 |
  | DHT11 | 6 | GPIO4 |

* **Calibration, measured together on the board:**
  * soil: 0 in air, ~2350 in water;
  * light: 0 covered, ~1550 room light, ~3800 phone flashlight;
  * DHT11: 25.5 °C / 59 % in the room.
* **In `sensors.h`:** pins and calibration live here. 16-sample ADC averaging; a DHT retry after its 2 s
  cycle; a failed sensor reads `null`. Lux from the photoresistor is a rough estimate.
* **Checked:** serial readings followed the finger, flashlight and water tests. The phone read the unit over
  its Wi-Fi.

## 4. Full integration of the sensor unit into the app

The hardware is optional and modular: with no unit, the app is camera-only and no sensor UI appears.

* **Live link** (`sensors.ts`):
  * polls the unit every 5 s while it answers, every 10 s otherwise, and only while the app is open;
  * after pairing once, it connects by itself whenever the phone is on the unit's Wi-Fi;
  * two missed answers mark it disconnected.
* **Shown only for the sensors a reading actually has** (`SensorPanel.tsx`):
  * **Home and the device page:** a "Live sensors" card with plain-language notes (dry soil, thirsty air
    (VPD), too dark).
  * **Camera:** live values over the viewfinder. **Identify takes a fresh reading**, which goes with the photos
    into the diagnosis.
  * **Health check:** a "Sensor reading" card with Read again / Don't save it.
  * **Tree page:**
    * an "Add sensor reading" button (reading without photos), shown only with a unit connected;
    * sensor history, an environment summary and "since last visit" notes.
  * **Map:** Soil / Temp / Humidity / Light layers, shown only if some tree has that data.
* **Backend:**
  * tree summaries now include `latest_sensors`;
  * new `DELETE /observations/{id}/sensors` ("Don't save it"), which re-runs the diagnosis;
  * OpenAPI and the client types were regenerated.

## 5. The whole app runs on the phone ("Use on this phone only")

Nothing needs a computer or internet.

* **Recognition on the phone** (`mobile/src/engine/`):
  * Model Delta (`hemlock.onnx`, 87 MB) runs with ONNX Runtime inside the app;
  * photos are decoded at the server's exact scale; for 12 MP iPhone photos this raised the match with the
    server from 0.982 to 0.9998;
  * every photo is checked while scanning (blur, light, duplicate view, hemlock %);
  * the server's calibrated decision says existing tree / new tree / not sure;
  * fingerprints are saved per tree, so the next visit matches.
* **Hemlock check on the phone:** one photo per tree, the same verdict rule as the server.
* **Diagnosis on the phone** (`diagnosis.ts`): port of `diseases.py` (woolly adelgid, scale, drought) and
  `twin.py` (environment, since last visit, next action).
* **Insights on the phone** (`analysis.ts`, `conditionGuide.ts`):
  * port of `analysis.py`: disease rates, hotspots, quarterly trends, worst trees and advice;
  * sections saved on the phone, and "Analyze this view" on the map.
* **Phone database** (`data.ts`): SQLite, upgraded in place (v2 → v4) with checklist and severity, readings,
  fingerprints and sections. Old scans keep their diagnosis.
* **Model self-check screen:** Device and account → On-device model compares the phone's output with the
  server's on a known photo.

## 6. Battery and power for the sensor unit

Firmware `wifi-1.1.0` (`power.h`), flashed on the board:

* CPU at 80 MHz.
* Deep sleep after 30 minutes with no phone joined (press EN to wake).
* Optional battery level through two 100 kΩ resistors on GPIO36, with cut-off below 3.3 V.
* LED blink: every 3 s normally, every 1 s when the battery is low.

**App:** shows the battery on the Live sensors card and device page, and warns below 20 %.

**How to power it:** a USB power bank (no wiring), or an 18650 battery shield with optional level sensing.
See `esp32_wifi.md`.

## 7. Fixes and polish

* **Backend bug:** newer FastAPI reads an omitted form checkbox as false, so every scan sent from the app was a
  dry run and was never saved. Fixing `/identify` also fixed 17 old failing tests.
* **A review for real-iPhone issues** found 12 problems, all fixed:
  * Hemlock check was broken in phone-only mode;
  * screens looked empty when the server couldn't be reached (now an error with "Try again");
  * error messages are in plain language;
  * the pair screen was a dead end (now "Skip");
  * denied camera access now offers "Open Settings";
  * when location is off, the app now says so;
  * Local Network access is now only requested after pairing;
  * phone-only setup now shows progress and errors;
  * double taps are guarded;
  * library imports show progress and stop when the scan is closed.
* **Removed** a "Sync when online" switch that never synced anything.
* **Results show real species scores** (top 3, hemlock %) instead of "unknown 0 %".
* **Wording:** "1 tree", not "1 trees".
* **Keyboard** no longer covers the unit-address field. Camera sensor chips are compact.

## 8. Tests

**204 passed, 8 skipped, 0 failed** (`pytest`). App type check (`tsc`) and lint are clean.

| Test | What it checks |
|---|---|
| `test_esp32_wifi.py` | firmware JSON compiled on the computer; firmware and simulator routes match; Python client and CLI; the app's own client and live link against the simulated unit; battery curve; "Don't save it"; identify stores the visit |
| `test_phone_engine.py` | phone model output vs the server: fingerprint cosine 0.99999; 12 MP photo at 0.9998 |
| `test_phone_diagnosis.py` | 3,000 random visits plus 600 visit histories, identical to the Python |
| `test_phone_analysis.py` | 300 random forests: Insights identical to the Python; Python-style rounding; advice text identical |
| `test_phone_data.py` | phone database: upgrades, saving scans with readings and fingerprints, diagnosis, Insights and sections |

The test photo that was missing (`tests/data/astronaut_public_domain_256.jpg`) was added, so the face-blur
tests run.

## 9. Checked by hand

* **Real hardware:** the firmware is flashed, the sensors are calibrated, and the phone reads the unit over
  its Wi-Fi.
* **Your iPhone:** the standalone Release build is installed and runs with no Mac.
* **iOS simulator, standalone Release build, phone-only mode:**
  * onboarding → Skip → phone-only;
  * Hemlock check: bark 95 % hemlock, flowers 1 %;
  * scan with GPS → New tree H-043 saved on the map;
  * rescan with different photos → **Match found H-043, 100 %**;
  * Insights;
  * Analyze this view → save section → its outline on the map;
  * pairing the simulated unit → live sensors.
* **Speed on the phone:** model load ~0.2 s, then ~2 s per photo.

## 10. Known limits

* The map's background (Apple Maps) needs signal; the tree dots, layers and sections work without it.
* The streets and trails drawn on the map exist only for the server's demo forest.
* Model Gamma runs only on the server; the phone runs Delta.
* There is no automatic phone ↔ server sync; use Export data (CSV).
* A free Apple ID install expires after 7 days. Reinstall with
  `cd mobile && npx expo run:ios --device --configuration Release`.
* The unit's current draw wasn't measured, so the battery runtimes are estimates.
* Tooling notes:
  * Xcode 26 or newer is needed for the app build;
  * on macOS 27 the ESP32 toolchain needs Rosetta (`softwareupdate --install-rosetta`);
  * Xcode 27 has no Simulator app; drive simulators with `xcrun simctl` / idb.
