import { AppState } from 'react-native';
import { create } from 'zustand';
import type { Sensors } from './api';
import { autoConnect, useApp } from './device';
import { NodeUnreachable, nodeUrl, parseEsp32Reading, readOverWifi, READINGS } from './esp32';

// The live link to the ESP32 sensor unit. The rest of the app never talks to the unit directly: it reads
// `useSensors` and shows sensor sections only while a unit is connected (or a reading was taken), and only
// for the sensors the unit actually reports. Without a unit, everything works from the phone camera alone.

export type Live = { device: string; sensors: Sensors; at: number };

type State = {
  live: Live | null; // latest reading from the unit, while it is connected
  online: boolean; // the unit answered within the last two polls
  measuring: boolean;
};

export const useSensors = create<State>(() => ({ live: null, online: false, measuring: false }));

const POLL_ONLINE_MS = 5000;
const POLL_OFFLINE_MS = 10_000;
const FRESH_MS = 60_000;

/** Is a sensor unit connected right now? */
export const useConnected = () => {
  const on = useSensors((s) => s.online && s.live !== null);
  return useApp((s) => s.unit !== null) && on;
};

/** The keys this reading actually has (a sensor the unit lacks or that failed is null and is hidden). */
export const present = (s: Sensors | null | undefined) => (s ? READINGS.filter((r) => s[r.key] != null) : []);
export const hasAny = (s: Sensors | null | undefined) => present(s).length > 0;

async function getReading(): Promise<Live> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 3000);
  try {
    const res = await fetch(`${nodeUrl()}/api/v1/reading`, { signal: ctrl.signal });
    if (!res.ok) throw new NodeUnreachable(`HTTP ${res.status}`);
    const r = parseEsp32Reading(JSON.stringify(await res.json()));
    return { device: r.device ?? 'ESP32', sensors: r.sensors, at: Date.now() };
  } catch (e) {
    throw e instanceof NodeUnreachable ? e : new NodeUnreachable(String(e));
  } finally {
    clearTimeout(timer);
  }
}

let misses = 0;
async function tick() {
  const app = useApp.getState();
  if (!autoConnect() && !app.unit) return void useSensors.setState({ online: false }); // disconnected by the user
  try {
    const live = await getReading();
    misses = 0;
    // the user may have disconnected while this request was out: don't bring the unit back
    if (!autoConnect() && !useApp.getState().unit) return void useSensors.setState({ online: false });
    useSensors.setState({ live, online: true });
    // A unit answering on this network is connected, also after the app restarts or Wi-Fi comes back.
    if (app.unit?.id !== live.device && !app.connecting) await app.connect(live.device).catch(() => {});
  } catch {
    if (++misses >= 2 && useSensors.getState().online) {
      useSensors.setState({ online: false });
      useApp.setState({ unit: null }); // out of range; it reconnects by itself when it answers again
    }
  }
}

let started = false;
/** Start watching for the unit (once, from the root layout). Polls only while the app is in the foreground. */
export function startSensorLink() {
  if (started) return;
  started = true;
  // One loop at a time: coming back to the app restarts it (generation bumps), and a stale loop whose request
  // was still out when that happened stops instead of rescheduling itself.
  let timer: ReturnType<typeof setTimeout> | undefined;
  let generation = 0;
  const loop = async (gen: number) => {
    if (AppState.currentState === 'active') await tick();
    if (gen !== generation) return;
    timer = setTimeout(() => loop(gen), useSensors.getState().online ? POLL_ONLINE_MS : POLL_OFFLINE_MS);
  };
  AppState.addEventListener('change', (s) => {
    if (s !== 'active') return;
    clearTimeout(timer);
    loop(++generation); // check right away when the user comes back from the Wi-Fi settings
  });
  loop(generation);
}

/** Measure now (the unit takes a fresh reading). Throws if no unit answers. */
export async function measureNow(): Promise<Live> {
  useSensors.setState({ measuring: true });
  try {
    const r = await readOverWifi();
    const live = { device: r.device ?? 'ESP32', sensors: r.sensors, at: Date.now() };
    useSensors.setState({ live, online: true });
    return live;
  } finally {
    useSensors.setState({ measuring: false });
  }
}

/** The reading to attach to a scan or visit: a fresh one if a unit is connected, else null (camera only). */
export async function readingForVisit(): Promise<Live | null> {
  const { online, live } = useSensors.getState();
  if (!online || !useApp.getState().unit) return null; // no unit, or the user disconnected it
  try {
    return await measureNow();
  } catch {
    return live && Date.now() - live.at < FRESH_MS ? live : null;
  }
}

// ------------------------------------------------------------------ what a reading means
// Same thresholds as the backend's diagnosis (src/hemlock_sentinel/api/diseases.py), so the phone can explain a
// reading on its own (offline mode, live card) and agree with the server.
export const LIMITS = { drySoil: 15, warnSoil: 22, hot: 32, dryAir: 40, highVpd: 1.5, lowLight: 1000 } as const;

/** Vapour-pressure deficit (kPa, Tetens): how hard the air pulls water from the needles. */
export const vpd = (t: number, rh: number) => 0.6108 * Math.exp((17.27 * t) / (t + 237.3)) * (1 - rh / 100);

export type Note = { text: string; tone: 'good' | 'warn' | 'bad' };

/** Plain-language notes on one reading, only for the sensors it has. */
export function interpret(s: Sensors | null | undefined): Note[] {
  if (!s) return [];
  const out: Note[] = [];
  const soil = s.soil_moisture_pct, t = s.air_temp_c, h = s.humidity_pct, lux = s.light_lux;
  if (soil != null) {
    out.push(soil < LIMITS.drySoil ? { text: `Soil is dry (${Math.round(soil)}%): drought-stress risk.`, tone: 'bad' }
      : soil < LIMITS.warnSoil ? { text: `Soil is getting dry (${Math.round(soil)}%).`, tone: 'warn' }
      : { text: `Soil moisture is fine (${Math.round(soil)}%).`, tone: 'good' });
  }
  if (t != null && h != null) {
    const v = vpd(t, h);
    out.push(v >= LIMITS.highVpd ? { text: `Air is drying the tree fast (VPD ${v.toFixed(1)} kPa).`, tone: 'warn' }
      : { text: `Low water demand from the air (VPD ${v.toFixed(1)} kPa).`, tone: 'good' });
  } else if (t != null && t >= LIMITS.hot) {
    out.push({ text: `Hot (${Math.round(t)} °C): adds to water stress.`, tone: 'warn' });
  }
  if (lux != null && lux < LIMITS.lowLight) out.push({ text: 'Too dark to trust small signs: use the flash or check by hand.', tone: 'warn' });
  return out;
}
