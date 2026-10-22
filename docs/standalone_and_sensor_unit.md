# HemlockID standalone + the ESP32 sensor unit: what changed and how to use it offline

Branch `combined`: everything from `final`, the `results/rtx3060-barknet` run artifacts, and the work below.
Details live in [phone_only.md](phone_only.md) (the app with no computer) and [esp32_wifi.md](esp32_wifi.md)
(the sensor unit).

## What was done

**1. ESP32 sensor unit over its own Wi-Fi** (`firmware/esp32_wifi_node`, firmware `wifi-1.1.0`)
* The ESP32 makes its own Wi-Fi network (`HS-ESP32-xxxx`, password `hemlock-sentinel`) and serves a small JSON API
  at `http://192.168.4.1` (`/api/v1/status`, `/reading`, `/measure`, `/readings`). No router or internet needed.
* Real sensors, calibrated on our board: soil moisture (GPIO34), light (GPIO35), DHT11 air temperature and
  humidity (GPIO4), through the 37-kit shield powered at 3.3 V.
* Power saving for battery use: 80 MHz CPU, sleeps after 30 min with no phone joined (press EN to wake), optional
  battery level through a 2×100 kΩ divider on GPIO36, low-battery cut-off, status LED.
* Laptop side: `hemlock-esp32 read|log|visit --wifi` and `hemlock-esp32 simulate` (a fake unit for testing).

**2. Sensor data everywhere in the app, but only when a unit is there**
* After pairing once, the app connects by itself whenever the phone is on the unit's Wi-Fi.
* With a unit: live readings on Home and over the camera; each scan takes a fresh reading that goes into the
  drought diagnosis; health check, tree page, sensor history, battery level and low-battery warning.
* Map layers for Soil / Temp / Humidity / Light, shown only for sensors that have data.
* Without a unit, no sensor UI appears; the phone camera works exactly as before.

**3. Everything runs on the phone ("Use on this phone only")**
* The tree-recognition model (Model Delta, ONNX, 87 MB) runs on the phone: photo checks while scanning,
  matching a tree again on a later visit, and Hemlock check.
* The diagnosis (adelgid, scale, drought), the digital-twin notes and the forest Insights (disease rates,
  hotspots, trends, worst trees, advice, saved sections, "Analyze this view") were ported from the Python
  server to TypeScript.
* Tests show the phone gives the server's answers:
  * fingerprints are 99.999 % the same as the server's;
  * 3,000 random diagnoses and 600 visit histories match;
  * 300 random forests' Insights are identical.
* All data stays on the phone (SQLite).

**4. Fixes and polish**
* **Server bug:** with newer FastAPI, scans sent from the app were never saved. Fixing it also fixed 17
  old test failures.
* **Errors and dead ends:** plain-language errors; a "Try again" when the server can't be reached; no
  dead ends when the camera, location or Local Network permission is off; a "Skip" on the pair screen;
  double-tap guards.
* **Removed** a "Sync when online" switch that never synced anything.
* **Test suite:** 204 passed, 8 skipped, 0 failed.

**Verified:**
* On a real iPhone: the standalone build runs with no Mac, and the phone reads the real ESP32.
* In the iOS simulator, fully on the phone: Hemlock check, scan with GPS, recognizing the same tree
  again (100 %), Insights, saving a section, and sensor pairing.

## Using it offline (no computer, no internet)

### Once: install the app on the iPhone (needs the Mac, about 5 min)
1. Plug in the iPhone, tap **Trust**. On the iPhone: Settings → Privacy & Security → **Developer Mode** on.
2. On the Mac: Xcode → Settings → Accounts → sign in with your Apple ID (a free one works).
3. Build and install:
   ```bash
   cd mobile
   npm install                                   # also copies the model into the app
   npx expo run:ios --device --configuration Release
   ```
4. First launch: Settings → General → VPN & Device Management → your Apple ID → **Trust**.

With a free Apple ID the app stops opening after 7 days; repeat step 3 (your data stays).

### In the field
1. Open HemlockID → **Use on this phone only** → pick a forest (three sample forests are included, or add your own).
2. **Scan a tree**: 3 photos of the bark, a quarter turn around the trunk each time. The app coaches each photo,
   then says *Match found* (a tree you scanned before) or *New tree*. Fill in what you see and save.
3. **Hemlock check** (Home): one photo per tree, "is this a hemlock?".
4. **Insights** tab and the **Map** (Analyze this view, Sections) work without a connection.
5. Check it once: Device and account → **On-device model** should say *Works on this phone*.

Airplane mode is fine. The only thing that needs signal is the map's background (Apple Maps streets and terrain);
without it the tree dots still show on a blank background.

### With the sensor unit
1. Power the ESP32: USB from a power bank (easiest), or an 18650 battery shield (see
   [esp32_wifi.md → Run it on a battery](esp32_wifi.md#run-it-on-a-battery)).
   **Never** connect a battery to the 3V3 pin.
2. On the iPhone: Settings → Wi-Fi → **HS-ESP32-xxxx**, password `hemlock-sentinel`. Stay connected when it says
   "No internet".
3. First time only: in the app, avatar → **Pair a unit** → Connect. Allow **Local Network** when iOS asks.
4. From then on the **Live sensors** card appears by itself, and each scan takes a reading.
5. The unit sleeps after 30 minutes with no phone joined: press **EN** on the board to wake it.

Phone-only mode needs nothing else. Signed in to a server instead, switch back to normal Wi-Fi to save scans.

## Not covered

* Streams and trails drawn on the map exist only for the server's demo forest.
* The second recognition model, Gamma, is server-only; the phone runs Delta.
* No automatic sync between a phone and a server. Use Device and account → **Export data** (CSV).
* The battery runtimes in esp32_wifi.md are estimates; the unit's current draw was not measured.
