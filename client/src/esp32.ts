/**
 * The ESP32 sensor node (firmware/esp32_sensors): Bluetooth LE identifiers and reading parser.
 *
 * React Native (react-native-ble-plx), roughly:
 *   const dev = await manager.connectToDevice(id).then((d) => d.discoverAllServicesAndCharacteristics());
 *   await dev.writeCharacteristicWithoutResponseForService(ESP32.service, ESP32.command, base64("r"));
 *   await sleep(ESP32.measureWaitMs);
 *   const c = await dev.readCharacteristicForService(ESP32.service, ESP32.reading);
 *   const { sensors } = parseEsp32Reading(atob(c.value!));
 *   await api.identify(photos, { sensors, location });   // or api.addVisit(treeId, { sensors })
 * Scan with manager.startDeviceScan([ESP32.service], null, cb) and pick names starting "HS-ESP32".
 */
import type { components } from "./schema";

export const ESP32 = {
  service: "6e1f0001-6d6c-4f2b-9a35-1c3a5e6b7d01",
  reading: "6e1f0002-6d6c-4f2b-9a35-1c3a5e6b7d01", // read / notify: JSON
  command: "6e1f0003-6d6c-4f2b-9a35-1c3a5e6b7d01", // write "r": measure now
  namePrefix: "HS-ESP32",
  measureWaitMs: 3000,
} as const;

export type Esp32Reading = { device: string | null; sensors: components["schemas"]["Sensors"]; raw: Record<string, unknown> };

const RANGES: Record<string, [number, number]> = {
  soil_moisture_pct: [0, 100], air_temp_c: [-40, 60], humidity_pct: [0, 100], light_lux: [0, 200000],
};

/** Firmware JSON -> sensors for the API. A failed or out-of-range sensor becomes null (N/A). */
export function parseEsp32Reading(json: string): Esp32Reading {
  // BLE stacks can pad the value with NUL bytes; serial lines end in \r\n
  const d = JSON.parse(json.replace(/\0+/g, "").trim());
  if (!d || d.v !== 1) throw new Error("not a Hemlock Sentinel ESP32 reading");
  const sensors: Record<string, number | null> = {};
  for (const [k, [lo, hi]] of Object.entries(RANGES)) {
    const v = d[k] == null ? null : Number(d[k]);
    sensors[k] = v != null && Number.isFinite(v) && v >= lo && v <= hi ? v : null;
  }
  return { device: d.device ?? null, sensors: sensors as Esp32Reading["sensors"], raw: d };
}
