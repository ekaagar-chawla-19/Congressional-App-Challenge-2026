// The phone app's Wi-Fi client (src/esp32.ts) and unit link (src/device.ts) against a node at argv[2]
// (a real one, or `hemlock-esp32 simulate`). Prints one JSON object. Used by tests/integration/test_esp32_wifi.py:
//   node --experimental-strip-types --no-warnings --import ./test/register-stubs.mjs test/esp32wifi.mjs http://127.0.0.1:8090
const esp = await import("../src/esp32.ts");
const { link } = await import("../src/device.ts");

const url = process.argv[2];
const out = {};
const attempt = async (name, f) => {
  try {
    out[name] = await f();
  } catch (e) {
    out[name] = { error: e.message, unreachable: e instanceof esp.NodeUnreachable };
  }
};

await attempt("unreachable_default", () => esp.nodeStatus("http://127.0.0.1:9"));
esp.setNodeUrl(url.replace(/^http:\/\//, "")); // a bare host:port gets http:// added
out.node_url = esp.nodeUrl();
await attempt("status", () => esp.nodeStatus());
await attempt("measure", () => esp.readOverWifi());
await attempt("log", async () => (await esp.readLogOverWifi(0)).map((r) => ({ seq: r.seq, sensors: r.sensors, age_s: Math.round((Date.now() - r.takenAt) / 1000) })));
await attempt("discover", () => link.discover());
await attempt("connect", async () => link.connect((await link.discover())[0].id));
await attempt("connect_wrong", () => link.connect("HS-ESP32-NOPE"));
// the live link (src/sensors.ts): a scan gets a fresh reading while a unit is online, none without one
const sensors = await import("../src/sensors.ts");
const { useApp } = await import("../src/device.ts");
sensors.useSensors.setState({ online: true, live: null });
useApp.setState({ unit: { id: "HS-ESP32-SIM0", name: "HS-ESP32-SIM0", signal: "Strong", battery: null, storage: "", firmware: "" } });
await attempt("visit_reading", () => sensors.readingForVisit());
useApp.setState({ unit: null }); // disconnected by the user: no reading, even if the link still looks online
await attempt("visit_reading_disconnected", () => sensors.readingForVisit());
sensors.useSensors.setState({ online: false });
await attempt("visit_reading_no_unit", () => sensors.readingForVisit());
out.present = sensors.present({ soil_moisture_pct: 12, air_temp_c: null, humidity_pct: null, light_lux: 300 }).map((r) => r.key);
out.notes = sensors.interpret({ soil_moisture_pct: 12, air_temp_c: 30, humidity_pct: 20, light_lux: 300 }).map((n) => n.tone);
esp.setNodeUrl(esp.NODE.defaultUrl);
out.node_url_reset = esp.nodeUrl();
console.log(JSON.stringify(out));
