# Phone-only mode and the sensor unit in the app

HemlockID has two modes, chosen at sign-in:

| | Signed in to a server | **On this phone only** |
|---|---|---|
| Tree identification (Model Delta) | on the computer (`hemlock-api`) | **on the phone** (ONNX Runtime), in the app build; Expo Go: pick the tree by hand |
| Database | the server's, per forest | the phone's SQLite (`hemlockid.db`) |
| Diagnosis (HWA, scale, drought) | `api/diseases.py` | **`mobile/src/diagnosis.ts`**, the same rules, checked to give identical answers |
| Digital twin (environment, "since last visit", next action) | `api/twin.py` | `mobile/src/diagnosis.ts` |
| Map sensor layers, sensor history | yes | yes |
| Needs a computer or internet | yes | **no** |

The ESP32 sensor unit is optional in both modes. The phone camera works the same with or without it.

## The sensor unit in the app

`mobile/src/sensors.ts` keeps a live link to the unit (firmware: `firmware/esp32_wifi_node`, see
[esp32_wifi.md](esp32_wifi.md)):

* **It connects by itself.** While the app is open, it asks `http://192.168.4.1/api/v1/reading`: every 5 s while
  the unit answers, every 10 s while it doesn't. When the phone joins the unit's Wi-Fi, the unit appears without
  pairing. Two missed answers mark it disconnected. "Disconnect unit" stops the automatic connection until the
  unit is paired again.
* **Sensor sections show only when there is something to show.** Without a unit and without stored readings,
  no sensor UI appears anywhere. With one, each section shows only the sensors the reading has: a unit with just
  a soil probe shows just soil moisture.

| Where | With a unit connected | Without |
|---|---|---|
| Home | "Live sensors" card: values, what they mean, Measure | nothing |
| Camera | live values over the viewfinder; **Identify takes a fresh reading** that goes with the photos | camera only |
| Health check | "4. Sensor reading": the reading taken with the photos, Read again, Don't save it | section hidden |
| Tree page | "Add sensor reading" button | hidden |
| Tree page, map, insights | latest reading, sensor history, environment summary, sensor map layers | shown only for trees and forests that have readings |

The reading taken at Identify is sent with the photos to the server (`POST /captures/{id}/identify`, field
`sensors`), so the first diagnosis already uses it. In phone-only mode it is stored with the scan.

**Map layers.** Besides Health / Adelgid / Scale / Drought, the map gets a layer for each sensor that at least one
tree has a reading for: Soil (dry < 15 %, getting dry < 22 %, moist), Temp (cool < 10 °C, mild, hot ≥ 32 °C),
Humidity (dry air < 40 %, normal, humid ≥ 75 %) and Light (too dark < 1000 lux). These bands are the diagnosis
thresholds. Tapping a tree shows its reading.

## On-device identification

`mobile/src/engine/` runs Model Delta (`models/production/hemlock.onnx`, 87 MB, copied into
`mobile/assets/models/` by `npm install`):

1. Each photo is checked as it is taken: blur, exposure, duplicate view, and hemlock probability. The camera
   coaches the same way the server's guided capture does.
2. **Identify** averages the accepted trunk views and searches the forest's stored fingerprints (table
   `fingerprints`, one per accepted view, tagged with the model version). It uses the server's calibrated decision
   (existing / new / not sure, with the same thresholds).
3. The fingerprints are saved with the tree the scan is saved to, so the next visit can be matched.

`engine/ondevice.ts` is a byte-for-byte copy of `client/src/ondevice.ts`, the shared port that the client tests
check against the server (11 of 11 held-out hemlock decisions identical). Only its Gallery type differs.

**Running it needs the app build, not Expo Go**, because ONNX Runtime is native code. The build needs Xcode 26 or
newer (Swift 6.2+); it was built and tested with Xcode 27.1 on macOS 27.

### Install on an iPhone (standalone: no Mac or dev server needed afterwards)

1. Plug the iPhone into the Mac and tap **Trust**.
2. On the iPhone: **Settings → Privacy & Security → Developer Mode → On** (it restarts).
3. On the Mac: Xcode → **Settings → Accounts → +** → sign in with your Apple ID (a free account works).
4. Build and install the release version:
   ```bash
   cd mobile
   npm install                                    # also copies the model into assets/models
   npx expo run:ios --device --configuration Release
   ```
   Pick your iPhone from the list. The first time, Xcode may ask you to choose your "team" (your Apple ID):
   open `mobile/ios/HemlockID.xcworkspace`, select the HemlockID target → Signing & Capabilities → Team.
5. The first time you open it, the iPhone may say the developer is untrusted: **Settings → General → VPN & Device
   Management → your Apple ID → Trust**.

With a free Apple ID the app stops opening after 7 days. Run step 4 again to reinstall; your data stays. In the
app, **Device and account → On-device model** runs a check that the model works on that phone.

In Expo Go everything else works: the model is simply not available there, and identification falls back to
picking the tree by hand.

## Tested

| Test | What it checks |
|---|---|
| `tests/integration/test_phone_diagnosis.py` | 3000 random visits and 600 multi-visit trees: phone diagnosis and digital twin text identical to the Python |
| `tests/integration/test_phone_engine.py` | the engine copy equals the shared port; on the server's recorded photo, decoded like the phone (no `Buffer`), fingerprint cosine 0.99999 and hemlock probability within 0.002 of the server; a 12 MP photo is decoded at the server's scale (756×1008, cosine 0.9998); fingerprint storage exact |
| `tests/integration/test_phone_data.py` | phone database: v2 → v3 upgrade, saving scans with checklist + reading + fingerprints, reading-only visits, diagnosis on the phone, camera-only trees without sensor data, delete |
| `tests/integration/test_esp32_wifi.py` | the app's Wi-Fi client and live link against the simulated unit: fresh reading at Identify, none without a unit or after disconnecting, only present sensors shown; a visit's reading can be removed ("Don't save it"); one-shot identify stores the visit |
| `npx tsc --noEmit`, `npx expo lint`, `npx expo export --platform ios` | app types, lint, and the iOS JavaScript bundle (with the model asset) |

**In the app, on the iOS simulator (Xcode 27.1, iPhone 16 Pro), checked by hand with the real build:**

* On-device model check: fingerprint 99.999 % the same as the server's, hemlock probability 10.2 % vs 10.1 %.
* Phone-only scan with real hemlock bark (an openly licensed iNaturalist photo, CC0/CC-BY): each photo coached on
  the phone ("Good photo. Hemlock bark 96 %"), *No close match → New tree H-043*, then a rescan with different
  photos of the same bark: **Match found, H-043, very likely 100 %, Model Delta (on this phone)**.
* With the simulated unit (`hemlock-esp32 simulate`): it connects by itself. The home screen shows the live card,
  the camera shows live values, Identify attaches a fresh reading, the health check shows it, and the tree page
  shows it with the drought assessment it caused. The map shows Soil / Temp / Humidity / Light layers. When the unit
  goes away, the sensor UI disappears within about 20 s, and it comes back by itself.
* The Release build (JavaScript inside the app) runs without the dev server.

Not tested: a physical iPhone (that needs your phone and Apple ID, see above).
