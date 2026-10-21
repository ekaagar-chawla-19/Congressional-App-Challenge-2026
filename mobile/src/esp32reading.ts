import type { Sensors } from './api';

// The ESP32 sensor node's reading format, with no React Native imports so Node can run it in the backend's
// firmware test (tests/integration/test_esp32_simulated.py). Same rules as src/hemlock_sentinel/esp32/reading.py.
// label, unit and valid range of each reading (a value outside the range means the sensor failed)
export const READINGS: { key: keyof Sensors; label: string; unit: string; min: number; max: number }[] = [
  { key: 'soil_moisture_pct', label: 'Soil moisture', unit: '%', min: 0, max: 100 },
  { key: 'air_temp_c', label: 'Air temp', unit: '°C', min: -40, max: 60 },
  { key: 'humidity_pct', label: 'Humidity', unit: '%', min: 0, max: 100 },
  { key: 'light_lux', label: 'Light', unit: 'lux', min: 0, max: 200000 },
];

export type Esp32Reading = { device: string | null; sensors: Sensors };

/** Firmware JSON -> sensors. A failed or out-of-range sensor becomes null (N/A). Throws if it is not a reading. */
export function parseEsp32Reading(json: string): Esp32Reading {
  let d: Record<string, unknown>;
  try {
    // BLE stacks can pad the value with NUL bytes; serial lines end in \r\n
    d = JSON.parse(json.replace(/\0+/g, '').trim());
  } catch {
    throw new Error('That is not a sensor reading. Copy the whole line the node prints, starting with {"v":1');
  }
  if (!d || typeof d !== 'object' || d.v !== 1) throw new Error('That is not a HemlockID ESP32 reading (it needs "v":1).');
  const sensors = {} as Sensors;
  for (const r of READINGS) {
    const v = d[r.key] == null ? null : Number(d[r.key]);
    sensors[r.key] = v != null && Number.isFinite(v) && v >= r.min && v <= r.max ? v : null;
  }
  return { device: typeof d.device === 'string' ? d.device : null, sensors };
}
