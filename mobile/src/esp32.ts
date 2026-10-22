import Storage from './kv';
import { parseEsp32Reading, type Esp32Reading } from './esp32reading';

export { parseEsp32Reading, READINGS, type Esp32Reading } from './esp32reading';

// The ESP32 sensor unit's Wi-Fi API (firmware/esp32_wifi_node). Readings are parsed with the same rules as the
// backend (src/hemlock_sentinel/esp32/reading.py). The live link built on this is sensors.ts.

// ------------------------------------------------------------------ Wi-Fi (firmware/esp32_wifi_node)
// The node is its own Wi-Fi network (HS-ESP32-xxxx). Once the phone has joined it, the node answers at
// http://192.168.4.1. Contract: firmware/esp32_wifi_node/esp32_wifi_node.ino and src/hemlock_sentinel/esp32/wifi.py
// (`hemlock-esp32 simulate` serves it from a computer; enter that address on the pair screen).
export const NODE = {
  defaultUrl: 'http://192.168.4.1',
  password: 'hemlock-sentinel', // AP_PASS in the firmware
  statusTimeoutMs: 3000,
  measureTimeoutMs: 8000, // a real DHT11 can need a 2 s retry
} as const;

const NODE_URL = 'nodeUrl';
export const nodeUrl = () => Storage.getItemSync(NODE_URL) || NODE.defaultUrl;
export function setNodeUrl(url: string) {
  const u = url.trim().replace(/\/+$/, '');
  if (!u || u === NODE.defaultUrl) Storage.removeItemSync(NODE_URL);
  else Storage.setItemSync(NODE_URL, /^https?:\/\//.test(u) ? u : `http://${u}`);
}

export type NodeStatus = {
  v: 1; device: string; firmware: string; uptime_s: number; simulated: boolean; clients: number;
  battery_pct: number | null; battery_v: number | null; latest_seq: number; log_count: number; log_every_s: number;
};

export class NodeUnreachable extends Error {}

async function nodeCall<T>(method: 'GET' | 'POST', path: string, timeoutMs: number, base = nodeUrl()): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(base + path, { method, signal: ctrl.signal });
  } catch {
    throw new NodeUnreachable(base === NODE.defaultUrl
      ? `Can't reach the sensor unit. In Settings > Wi-Fi, join HS-ESP32-xxxx (password ${NODE.password}), then try again.`
      : `Can't reach the sensor unit at ${base}.`);
  } finally {
    clearTimeout(timer);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.error?.message ?? `The sensor unit answered HTTP ${res.status}`);
  return body as T;
}

export const nodeStatus = (base?: string) => nodeCall<NodeStatus>('GET', '/api/v1/status', NODE.statusTimeoutMs, base);

/** Ask the node to measure now and return that reading (same parsing as a pasted line). */
export async function readOverWifi(): Promise<Esp32Reading> {
  const raw = await nodeCall<Record<string, unknown>>('POST', '/api/v1/measure', NODE.measureTimeoutMs);
  return parseEsp32Reading(JSON.stringify(raw));
}

export type LoggedReading = Esp32Reading & { seq: number; takenAt: Date };

/** Readings the node logged on its own (seq > since), with the time each was taken. */
export async function readLogOverWifi(since = 0): Promise<LoggedReading[]> {
  const out: LoggedReading[] = [];
  for (;;) {
    const page = await nodeCall<{ readings: Record<string, unknown>[]; uptime_s: number; more: boolean }>(
      'GET', `/api/v1/readings?since=${since}`, NODE.statusTimeoutMs);
    const now = Date.now(); // the node has no clock: its uptime now vs. then gives the time
    for (const r of page.readings) {
      const seq = Number(r.seq);
      out.push({ ...parseEsp32Reading(JSON.stringify(r)), seq, takenAt: new Date(now - (page.uptime_s - Number(r.uptime_s)) * 1000) });
      since = Math.max(since, seq);
    }
    if (!page.more) return out;
  }
}
