# ESP32 sensor unit over Wi-Fi

The sensor unit is an ESP32 that makes **its own Wi-Fi network**. The phone joins that network and asks
the unit for readings over plain HTTP. No router, internet, Bluetooth library or development build is
needed. It works in Expo Go and in any browser.

```
 ESP32 (access point 192.168.4.1)  ◀── Wi-Fi "HS-ESP32-xxxx" ──▶  phone (HemlockID app)
   sensors.h  → reading                                           Pair screen, "Read from ESP32"
   HTTP JSON API (below)                                              │
                                                                      └── later, on normal Wi-Fi ──▶ hemlock-api
```

Firmware: [`firmware/esp32_wifi_node/`](../firmware/esp32_wifi_node/). The older Bluetooth sketch
(`firmware/esp32_sensors`) still works, but it needs Web Bluetooth or a native build, so iPhones could
only paste readings.

## Flash it

Arduino IDE: board **ESP32 Dev Module** (esp32 core 3.x), default partition scheme, open
`firmware/esp32_wifi_node/esp32_wifi_node.ino` → Upload. No extra libraries while sensors are simulated.
Or from a terminal:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/esp32_wifi_node
arduino-cli upload  --fqbn esp32:esp32:esp32 -p /dev/cu.usbserial-0001 firmware/esp32_wifi_node
```

At boot the Serial Monitor (115200) prints the network name, e.g.
`{"event":"ready","device":"HS-ESP32-1C49","ssid":"HS-ESP32-1C49","ip":"192.168.4.1",...}`, then one JSON
reading every 10 s. Type `r` to measure now.

| Setting (top of the .ino) | Default |
|---|---|
| Wi-Fi name | `HS-ESP32-xxxx` (from the chip ID) |
| Password `AP_PASS` | `hemlock-sentinel` |
| Address | `http://192.168.4.1` (also `http://hemlock.local` where mDNS works, e.g. iPhone) |
| Fresh reading every | 10 s (`READ_EVERY_MS`) |
| Logged reading every | 60 s, last 360 kept in RAM (`LOG_EVERY_MS`, `LOG_SIZE`); lost at power-off |

### Sensors and wiring

Three 3-pin kit modules plugged into a 37-kit (Uno-style) shield, which is jumpered to the ESP32. The shield's
`+` rail is fed **3.3 V**, never 5 V, because ESP32 pins are not 5 V tolerant.

| Shield pin | → ESP32 | |
|---|---|---|
| 5V | 3V3 | powers every `+` socket at 3.3 V |
| GND | GND | |
| A3 (soil sensor S) | GPIO34 | ADC1 (works with Wi-Fi on) |
| A2 (light sensor S) | GPIO35 | ADC1 |
| 6 (DHT11 D) | GPIO4 | |

Libraries: "DHT sensor library" (Adafruit) + "Adafruit Unified Sensor". Calibration, measured on our board
(raw 12-bit ADC, higher = wetter / brighter): soil 0 in air, ~2350 in water; light 0 covered, ~1550 room,
~3800 phone flashlight. The light module is a photoresistor, so `light_lux` is a rough estimate (also sent:
`light_raw`, `soil_raw`). Pins and calibration are at the top of `sensors.h`. Set `SIMULATE_SENSORS 1`
there to test the link on a bare board.

## API

All JSON, CORS open. Errors: `{"error":{"code":"…","message":"…"}}` with a 4xx status.

| Request | Answer |
|---|---|
| `GET /api/v1/status` | `{"v":1,"device","firmware","uptime_s","simulated","clients","battery_pct":null,"latest_seq","log_count","log_every_s"}` |
| `GET /api/v1/reading` | latest reading |
| `POST /api/v1/measure` | measures now and returns that reading (up to ~2.5 s with a DHT11) |
| `GET /api/v1/readings?since=N` | `{"readings":[…],"latest_seq","uptime_s","more"}`: logged readings with `seq > N`, oldest first, 50 per page. Repeat with the last `seq` while `more` is true |

A reading is the same v1 format as the Bluetooth node, plus `seq`:

```json
{"v":1,"device":"HS-ESP32-1C49","seq":12,"soil_moisture_pct":33.4,"air_temp_c":17.9,"humidity_pct":70,"light_lux":5954,"soil_raw":2581,"uptime_s":110}
```

A failed sensor is `null` and shows as N/A. The unit has no clock. A logged reading's time is
`now − (status uptime_s − reading uptime_s)`, which the app computes.

## Use it from the phone

1. Turn the unit on. On the phone: **Settings → Wi-Fi → HS-ESP32-xxxx**, password `hemlock-sentinel`.
   Stay connected when iOS/Android says "No internet".
2. Open HemlockID. The unit connects by itself within about 10 s: the home screen shows **Live sensors**, and the
   avatar dot turns green. (Pair screen: avatar → Pair a unit, for a different unit address.)
3. Scan a tree as usual. The viewfinder shows the live values, and **Identify takes a fresh reading** that goes
   with the photos into the diagnosis. The health check shows it again (Read again / Don't save it).
4. Without the unit everything works from the camera alone, and sensor sections don't appear.
   Details: [phone_only.md](phone_only.md).

In **phone-only mode** nothing else is needed: scans, readings and the diagnosis stay on the phone. Signed in to a
server, saving needs the backend. Either switch back to your usual Wi-Fi (the reading stays with the scan), or use
the demo setup below.

**Demo setup without switching:** have the computer running `hemlock-api` (and `expo start`) also join
`HS-ESP32-xxxx`. It gets an address like `192.168.4.2`. Point the app's server at
`http://192.168.4.2:8000`. Phone, unit and backend are now on one network, and the ESP32 relays between
them. The computer has no internet while joined, so start Expo with `npx expo start --offline`.

## Without the board

```bash
pip install -e ".[esp32]"
hemlock-esp32 simulate                       # same API on http://<this computer>:8090
```

In the app's Pair screen, tap **Unit address · Change** and enter `http://<computer-ip>:8090`. Laptop client:

```bash
hemlock-esp32 read --wifi                    # the real unit (after joining its Wi-Fi)
hemlock-esp32 read --wifi http://127.0.0.1:8090
hemlock-esp32 log  --wifi                    # everything it logged
hemlock-esp32 visit H-012 --wifi --forest 1 --email … --password …
```

## Tested

* On a real ESP32 (HS-ESP32-1C49, core 3.3.7): compiles (73 % flash), flashes, and boots as an access
  point at 192.168.4.1. Readings over USB go through `hemlock-esp32 read --serial`.
* `tests/integration/test_esp32_wifi.py`: the firmware's reading JSON compiled on a computer and parsed;
  firmware and simulator routes match; Python client and CLI (paging, `since`, 400/404, unreachable);
  the phone app's own `esp32.ts` / `device.ts` code under Node 22.6+ against the simulated node.
* A phone joining the unit's network and reading the sensors (Expo Go, real unit with the kit sensors).
  The full sensor UI was checked in the iOS simulator against `hemlock-esp32 simulate`
  ([phone_only.md](phone_only.md)).
