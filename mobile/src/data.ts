import { File, Paths } from 'expo-file-system';
import { useFocusEffect } from 'expo-router';
import type { SQLiteDatabase } from 'expo-sqlite';
import { useDb } from './db';
import { useCallback, useState } from 'react';
import { create } from 'zustand';
import { Platform } from 'react-native';
import * as api from './api';
import { PAIRED } from './device';
import Storage from './kv';
import { analyze, type SavedSection } from './analysis';
import { assess, currentConditions, environment, nextAction, sensorHistory, sinceLastVisit, type Visit } from './diagnosis';
import type { Live } from './sensors';
import { isServer, useSession } from './session';
import type { Status } from './theme';

export type Tree = { id: string; place: string; lat: number | null; lng: number | null; created_at: number };
// conditions: likelihood 0-1 per condition. sensors: the latest sensor reading (null: none ever taken).
export type TreeRow = Tree & { status: Status | null; last_scan: number | null; photo: string | null; conditions?: Record<string, number>; sensors?: api.Sensors | null };
export type Scan = { id: number; tree_id: string; created_at: number; photos: string; status: Status; note: string; synced: number; signs?: string; severity?: number | null } & Levels;
export type Forest = { id: number; name: string; lat: number | null; lng: number | null; trees: number; counts: Record<Status, number>; last_visit: number | null };
// Disease assessment and sensor readings: from the server, or worked out on the phone (diagnosis.ts) offline.
// history: per visit (oldest first), the likelihood of each condition assessed on that visit.
// The digital twin: every ESP32 reading (newest first), the readings fused into one sentence, what changed
// since the last visit and the next thing to do.
export type TreeExtras = {
  conditions: api.Finding[]; sensors: api.Sensors | null; history: { at: number; c: Record<string, number> }[];
  readings: api.SensorPoint[]; environment: api.Environment | null; changes: string[]; next: string | null;
};

// Health signs, scored 0 (none) to 3 (severe).
export const SIGNS = [
  { key: 'wool', label: 'White woolly masses' },
  { key: 'needles', label: 'Needle loss' },
  { key: 'crown', label: 'Thinning crown' },
  { key: 'dieback', label: 'Twig dieback' },
] as const;
export type Levels = Record<(typeof SIGNS)[number]['key'], number>;
export const LEVELS = ['None', 'Light', 'Moderate', 'Severe'];

// Visible woolly masses are the HWA signature, so moderate wool alone means infested.
// What the observer saw besides the four graded signs (all optional).
export type Checks = {
  twigsChecked: boolean; // looked under several low branches (otherwise insects are "not assessed")
  scale: boolean; // elongate hemlock scale covers under the needles
  banding: boolean; // yellow bands on needle tops
  browning: boolean; // browning / wilting in a dry spell
  borers: boolean; // small exit holes in the bark
  rootRot: boolean; // fungus fans / mushrooms at the base
};
export const NO_CHECKS: Checks = { twigsChecked: false, scale: false, banding: false, browning: false, borers: false, rootRot: false };

export const overall = (l: Levels, c: Checks = NO_CHECKS): Status => {
  const worst = Math.max(...Object.values(l));
  if (l.wool >= 2 || worst >= 3) return 'infested';
  return worst >= 1 || c.scale || c.banding || c.browning || c.borers || c.rootRot ? 'watch' : 'healthy';
};

export const REVISIT_DAYS = 30;
const DAY = 86_400_000;

export async function migrate(db: SQLiteDatabase) {
  await db.execAsync(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS trees (
      id TEXT PRIMARY KEY, place TEXT NOT NULL, lat REAL, lng REAL, created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS scans (
      id INTEGER PRIMARY KEY AUTOINCREMENT, tree_id TEXT NOT NULL REFERENCES trees(id), created_at INTEGER NOT NULL,
      photos TEXT NOT NULL, wool INTEGER, needles INTEGER, crown INTEGER, dieback INTEGER,
      status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', synced INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS scans_tree ON scans(tree_id, created_at DESC);`);
  const { user_version: v } = (await db.getFirstAsync<{ user_version: number }>('PRAGMA user_version'))!;
  if (v < 2) {
    // v2: trees belong to a forest. Trees from before that go into "My trees".
    await db.execAsync(`
      CREATE TABLE IF NOT EXISTS forests (id INTEGER PRIMARY KEY, name TEXT NOT NULL, lat REAL, lng REAL);
      ALTER TABLE trees ADD COLUMN forest_id INTEGER REFERENCES forests(id);
      PRAGMA user_version = 2;`);
    if (await db.getFirstAsync('SELECT 1 FROM trees')) {
      await db.runAsync("INSERT INTO forests (id, name) VALUES (1, 'My trees')");
      await db.runAsync('UPDATE trees SET forest_id = 1');
    }
  }
  if (v < 3) {
    // v3 (phone-only mode): the checklist as the server's sign keys + severity, so the phone can diagnose;
    // sensor readings (with a scan, or on their own); tree fingerprints for the on-device model.
    await db.execAsync(`
      ALTER TABLE scans ADD COLUMN signs TEXT NOT NULL DEFAULT '[]';
      ALTER TABLE scans ADD COLUMN severity INTEGER;
      CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tree_id TEXT NOT NULL REFERENCES trees(id), scan_id INTEGER REFERENCES scans(id),
        created_at INTEGER NOT NULL, soil_moisture_pct REAL, air_temp_c REAL, humidity_pct REAL, light_lux REAL, device TEXT);
      CREATE INDEX IF NOT EXISTS readings_tree ON readings(tree_id, created_at);
      CREATE TABLE IF NOT EXISTS fingerprints (
        tree_id TEXT NOT NULL REFERENCES trees(id), scan_id INTEGER REFERENCES scans(id), view_index INTEGER NOT NULL,
        model TEXT NOT NULL, embedding_b64 TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS fingerprints_model ON fingerprints(model, tree_id);`);
    // Scans from before v3 only have the four graded signs: derive the checklist from them (as the demo seed
    // does), so their trees keep a diagnosis.
    const old = await db.getAllAsync<Levels & { id: number }>('SELECT id, wool, needles, crown, dieback FROM scans');
    for (const sc of old) {
      const l = { wool: sc.wool ?? 0, needles: sc.needles ?? 0, crown: sc.crown ?? 0, dieback: sc.dieback ?? 0 };
      const { signs, severity } = toServer(l, { ...NO_CHECKS, twigsChecked: true });
      await db.runAsync('UPDATE scans SET signs = ?, severity = ? WHERE id = ?', JSON.stringify([...new Set(signs)]), severity, sc.id);
    }
    await db.execAsync('PRAGMA user_version = 3;');
  }
  if (v < 4) {
    // v4: named sections of a forest (a rectangle on the map), analysed on the phone like the server's.
    await db.execAsync(`
      CREATE TABLE IF NOT EXISTS sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT, forest_id INTEGER NOT NULL REFERENCES forests(id), name TEXT NOT NULL,
        west REAL NOT NULL, south REAL NOT NULL, east REAL NOT NULL, north REAL NOT NULL, created_at INTEGER NOT NULL);
      PRAGMA user_version = 4;`);
  }
}

// Sample forests for the offline demo: hemlock stands along North Georgia streams.
const DEMO_FORESTS: { name: string; lat: number; lng: number; bearing: number; places: string[] }[] = [
  { name: 'Cloudland Canyon State Park', lat: 34.8335, lng: -85.4816, bearing: 35, places: ['Daniel Creek', 'Sitton Gulch Trail', 'Hemlock Falls', 'West Rim Overlook'] },
  { name: 'Cooper Creek, Chattahoochee NF', lat: 34.759, lng: -84.07, bearing: 110, places: ['Cooper Creek Trail', 'Mill Shoals', 'Yellow Mountain', 'Bryant Creek'] },
  { name: 'Vogel State Park', lat: 34.7656, lng: -83.9255, bearing: 160, places: ['Wolf Creek', 'Trahlyta Lake', 'Bear Hair Gap'] },
];

export async function seedDemo(db: SQLiteDatabase) {
  if (await db.getFirstAsync("SELECT 1 FROM forests WHERE name = 'Cloudland Canyon State Park'")) return;
  let x = 7; // small deterministic generator so every demo looks the same
  const rnd = () => ((x = (x * 16807) % 2147483647) - 1) / 2147483646;
  const now = Date.now();
  const lvl = (base: number) => Math.max(0, Math.min(3, Math.round(base + (rnd() - 0.5) * 1.2)));
  let n = ((await db.getFirstAsync<{ n: number | null }>('SELECT MAX(CAST(SUBSTR(id, 3) AS INTEGER)) AS n FROM trees'))?.n ?? 0);
  await db.withTransactionAsync(async () => {
    for (const f of DEMO_FORESTS) {
      const { lastInsertRowId: fid } = await db.runAsync('INSERT INTO forests (name, lat, lng) VALUES (?, ?, ?)', f.name, f.lat, f.lng);
      const b = (f.bearing * Math.PI) / 180;
      for (let i = 0; i < 14; i++) {
        // along the stream, a few tens of metres either side; HWA spreading from the downstream end
        const along = (rnd() - 0.5) * 900, across = (rnd() - 0.5) * 70;
        const lat = f.lat + (along * Math.cos(b) - across * Math.sin(b)) / 111_320;
        const lng = f.lng + (along * Math.sin(b) + across * Math.cos(b)) / (111_320 * Math.cos((f.lat * Math.PI) / 180));
        const spread = ((along + 450) / 900) * 3;
        const id = `H-${String(++n).padStart(3, '0')}`;
        const visits = 1 + Math.floor(rnd() * 3);
        const first = now - (200 + rnd() * 400) * DAY;
        await db.runAsync('INSERT INTO trees VALUES (?, ?, ?, ?, ?, ?)', id, f.places[Math.floor(rnd() * f.places.length)], lat, lng, first, fid);
        for (let v = 0; v < visits; v++) {
          const at = Math.min(first + v * (90 + rnd() * 100) * DAY, now - (2 + rnd() * 40) * DAY);
          const base = spread - (visits - 1 - v) * 0.7;
          const l: Levels = { wool: lvl(base), needles: lvl(base - 0.5), crown: lvl(base - 1), dieback: lvl(base - 1.5) };
          const { signs, severity } = toServer(l, { ...NO_CHECKS, twigsChecked: true });
          const { lastInsertRowId: sid } = await db.runAsync(
            'INSERT INTO scans (tree_id, created_at, photos, wool, needles, crown, dieback, status, synced, signs, severity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)',
            id, at, '[]', l.wool, l.needles, l.crown, l.dieback, overall(l), JSON.stringify(signs), severity);
          if (rnd() < 0.75) {
            const month = new Date(at).getUTCMonth();
            const warm = month >= 4 && month <= 8;
            await db.runAsync('INSERT INTO readings (tree_id, scan_id, created_at, soil_moisture_pct, air_temp_c, humidity_pct, light_lux, device) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
              id, sid, at, Math.round((38 - base * 7 + (rnd() - 0.5) * 12) * 10) / 10, Math.round(((warm ? 24 : 9) + (rnd() - 0.5) * 8) * 10) / 10,
              Math.round(55 + (rnd() - 0.5) * 40), Math.round(400 + rnd() * 9000), 'demo');
          }
        }
      }
    }
  });
}

const forestId = () => useSession.getState().forest?.id ?? -1;
const ms = (iso: string | null) => (iso ? Date.parse(iso) : null);
// Server severity 0-3 (observer rating) to the app's status.
const statusOf = (sev: number | null): Status => (sev == null ? 'unrated' : sev === 0 ? 'healthy' : sev === 1 ? 'watch' : 'infested');
// The main condition with how sure the server is ("Woolly adelgid likely"), so a tree rated healthy
// by the observer but with a possible pest reads as a lead to check, not a contradiction.
const conditionLabel = (t: api.TreeSummary) => {
  const name = ({ hwa: 'Woolly adelgid', ehs: 'Hemlock scale', drought_stress: 'Drought stress' } as Record<string, string>)[t.main_condition ?? ''];
  const f = t.main_condition ? t.conditions?.[t.main_condition] : undefined;
  if (name) return f && f.level !== 'likely' ? `${name} possible` : `${name} likely`;
  return t.severity === 0 ? 'No problems found' : 'No condition confirmed';
};

export async function listForests(db: SQLiteDatabase): Promise<Forest[]> {
  if (isServer()) {
    return (await api.forests()).map((f) => {
      const c = f.severity_counts;
      return {
        id: f.forest_id, name: f.name, lat: f.center?.lat ?? null, lng: f.center?.lon ?? null, trees: f.tree_count, last_visit: ms(f.last_visit_at),
        counts: { healthy: c.none ?? 0, watch: c.light ?? 0, infested: (c.moderate ?? 0) + (c.severe ?? 0), unrated: c.unrated ?? 0 },
      };
    });
  }
  const forests = await db.getAllAsync<{ id: number; name: string; lat: number | null; lng: number | null }>('SELECT * FROM forests ORDER BY id');
  return Promise.all(forests.map(async (f) => {
    const rows = await db.getAllAsync<TreeRow>(LIST_SQL, f.id);
    const counts = { healthy: 0, watch: 0, infested: 0, unrated: 0 };
    for (const r of rows) counts[r.status ?? 'unrated']++;
    return { ...f, trees: rows.length, counts, last_visit: Math.max(0, ...rows.map((r) => r.last_scan ?? 0)) || null };
  }));
}

// ------------------------------------------------------------------ phone-only health
// The visits of some trees, oldest first, as the diagnosis sees them: each scan with its checklist and reading,
// plus readings taken on their own. findings: diagnosis.assess, exactly as the server would store them.
const READING_COLS = 'soil_moisture_pct, air_temp_c, humidity_pct, light_lux';
type ReadingRow = { id: number; tree_id: string; scan_id: number | null; created_at: number } & api.Sensors;
const sensorsOf = (r: ReadingRow | undefined): api.Sensors | null =>
  r && [r.soil_moisture_pct, r.air_temp_c, r.humidity_pct, r.light_lux].some((v) => v != null)
    ? { soil_moisture_pct: r.soil_moisture_pct, air_temp_c: r.air_temp_c, humidity_pct: r.humidity_pct, light_lux: r.light_lux } : null;

async function localVisits(db: SQLiteDatabase, where: string, arg: string | number): Promise<Map<string, Visit[]>> {
  const scans = await db.getAllAsync<Scan>(`SELECT s.* FROM scans s JOIN trees t ON t.id = s.tree_id WHERE ${where}`, arg);
  const readings = await db.getAllAsync<ReadingRow>(`SELECT r.id, r.tree_id, r.scan_id, r.created_at, ${READING_COLS} FROM readings r JOIN trees t ON t.id = r.tree_id WHERE ${where}`, arg);
  const byScan = new Map(readings.filter((r) => r.scan_id != null).map((r) => [r.scan_id!, r]));
  const out = new Map<string, Visit[]>();
  const push = (tree: string, v: Omit<Visit, 'findings'>, hasImages: boolean) => {
    const findings = assess(v.signs, v.sensors, v.severity, v.at, hasImages);
    out.set(tree, [...(out.get(tree) ?? []), { ...v, findings }]);
  };
  for (const sc of scans) {
    const signs = JSON.parse(sc.signs ?? '[]') as string[];
    push(sc.tree_id, { id: `s${sc.id}`, at: sc.created_at, severity: sc.severity ?? null, signs, sensors: sensorsOf(byScan.get(sc.id)) }, sc.photos !== '[]');
  }
  for (const r of readings) if (r.scan_id == null) push(r.tree_id, { id: `r${r.id}`, at: r.created_at, severity: null, signs: [], sensors: sensorsOf(r) }, false);
  for (const v of out.values()) v.sort((a, b) => a.at - b.at);
  return out;
}

// ------------------------------------------------------------------ insights (phone-only mode)
// The server's forest analysis, computed on the phone from this forest's visits (analysis.ts).
async function forestInput(db: SQLiteDatabase) {
  const trees = await db.getAllAsync<Tree>('SELECT * FROM trees WHERE forest_id = ?', forestId());
  const visits = await localVisits(db, 't.forest_id = ?', forestId());
  return trees.map((t) => ({ id: t.id, lat: t.lat, lon: t.lng, visits: visits.get(t.id) ?? [] }));
}
async function localSections(db: SQLiteDatabase): Promise<SavedSection[]> {
  const rows = await db.getAllAsync<{ id: number; name: string; west: number; south: number; east: number; north: number }>(
    'SELECT * FROM sections WHERE forest_id = ? ORDER BY name', forestId());
  return rows.map((r) => ({ section_id: r.id, name: r.name, bbox: [r.west, r.south, r.east, r.north] }));
}

/** Insights for the forest or a map area: from the server, or worked out on the phone in phone-only mode. */
export async function forestAnalysis(db: SQLiteDatabase, bbox?: api.Bbox): Promise<api.Analysis> {
  if (isServer()) return api.analysis(bbox);
  return analyze(await forestInput(db), await localSections(db), bbox);
}

export async function sectionAnalysis(db: SQLiteDatabase, id: number): Promise<api.Analysis> {
  if (isServer()) return api.sectionAnalysis(id);
  const sec = (await localSections(db)).find((s) => s.section_id === id);
  if (!sec) throw new Error('This section was deleted.');
  return { ...analyze(await forestInput(db), [], sec.bbox), section: sec };
}

export async function createSection(db: SQLiteDatabase, name: string, b: api.Bbox): Promise<{ section_id: number }> {
  if (isServer()) return api.createSection(name, b);
  if ((await localSections(db)).some((s) => s.name.toLowerCase() === name.trim().toLowerCase())) throw new Error(`A section called "${name.trim()}" already exists.`);
  const r = await db.runAsync('INSERT INTO sections (forest_id, name, west, south, east, north, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
    forestId(), name.trim(), b[0], b[1], b[2], b[3], Date.now());
  return { section_id: r.lastInsertRowId };
}

export async function deleteSection(db: SQLiteDatabase, id: number) {
  if (isServer()) return api.deleteSection(id);
  await db.runAsync('DELETE FROM sections WHERE id = ? AND forest_id = ?', id, forestId());
}

// Each tree with its latest scan.
const LIST_SQL = `
    SELECT t.*, s.status, s.created_at AS last_scan, json_extract(s.photos, '$[0]') AS photo
    FROM trees t LEFT JOIN scans s ON s.id = (SELECT id FROM scans WHERE tree_id = t.id ORDER BY created_at DESC LIMIT 1)
    WHERE t.forest_id = ? ORDER BY s.created_at DESC`;

export async function listTrees(db: SQLiteDatabase): Promise<TreeRow[]> {
  if (!isServer()) {
    const rows = await db.getAllAsync<TreeRow>(LIST_SQL, forestId());
    const visits = await localVisits(db, 't.forest_id = ?', forestId());
    return rows.map((r) => {
      const v = visits.get(r.id) ?? [];
      const hist = sensorHistory(v);
      return { ...r, sensors: hist[0]?.sensors ?? null,
        conditions: Object.fromEntries(currentConditions(v).map((f) => [f.condition, f.likelihood])) };
    });
  }
  return (await api.trees()).map((t) => ({
    id: t.tree_id, place: conditionLabel(t), lat: t.location?.lat ?? null, lng: t.location?.lon ?? null, created_at: Date.parse(t.created_at),
    status: statusOf(t.severity), last_scan: Date.parse(t.last_seen_at), photo: api.absolute(t.thumbnail_url),
    conditions: Object.fromEntries(Object.entries(t.conditions ?? {}).map(([k, f]) => [k, f.likelihood])),
    sensors: t.latest_sensors ?? null,
  }));
}

// Approximate 0-3 levels for the four signs from the server's checklist.
const levelsOf = (o: api.Observation): Levels => {
  const sev = Math.max(1, o.severity ?? 1);
  const has = (...k: string[]) => (k.some((x) => o.signs.includes(x)) ? sev : 0);
  return { wool: has('hwa_wool'), needles: has('needle_loss', 'needle_yellow_banding'), crown: has('gray_green_foliage', 'no_new_growth'), dieback: has('branch_dieback') };
};

export async function getTree(db: SQLiteDatabase, id: string): Promise<{ tree: Tree | null; scans: Scan[]; extras?: TreeExtras }> {
  if (!isServer()) {
    const visits = (await localVisits(db, 't.id = ?', id)).get(id) ?? [];
    const conditions = currentConditions(visits);
    const readings = sensorHistory(visits);
    const env = environment(readings);
    // suggest a sensor reading only to people who have a unit (demo readings don't count)
    const hasUnit = Storage.getItemSync(PAIRED) != null;
    return {
      tree: await db.getFirstAsync<Tree>('SELECT * FROM trees WHERE id = ?', id),
      scans: await db.getAllAsync<Scan>('SELECT * FROM scans WHERE tree_id = ? ORDER BY created_at DESC', id),
      extras: {
        conditions, sensors: readings[0]?.sensors ?? null, readings, environment: env, changes: sinceLastVisit(visits),
        next: visits.length ? nextAction(visits, conditions, env, hasUnit) : null,
        history: visits.filter((v) => v.findings.some((f) => f.level !== 'unknown')).map((v) => ({
          at: v.at, c: Object.fromEntries(v.findings.filter((f) => f.level !== 'unknown').map((f) => [f.condition, f.likelihood])),
        })),
      },
    };
  }
  const t = await api.tree(id).catch((e: api.ApiError) => (e.status === 404 ? null : Promise.reject(e)));
  if (!t) return { tree: null, scans: [] };
  return {
    tree: { id: t.tree_id, place: conditionLabel(t), lat: t.location?.lat ?? null, lng: t.location?.lon ?? null, created_at: Date.parse(t.created_at) },
    scans: t.observations.map((o, i) => ({
      id: i, tree_id: t.tree_id, created_at: Date.parse(o.timestamp), status: statusOf(o.severity), note: o.health_notes ?? '', synced: 1,
      photos: JSON.stringify(o.views.map((v) => api.absolute(v.image_url)).filter(Boolean)), ...levelsOf(o),
    })).reverse(),
    extras: {
      conditions: t.current_conditions, sensors: t.latest_sensors ?? null,
      readings: t.sensor_history ?? [], environment: t.environment ?? null, changes: t.since_last_visit ?? [], next: t.next_action ?? null,
      history: t.observations.map((o) => ({
        at: Date.parse(o.timestamp),
        c: Object.fromEntries(o.findings.filter((f) => f.level !== 'unknown').map((f) => [f.condition, f.likelihood])),
      })),
    },
  };
}

export const pendingCount = async (db: SQLiteDatabase) =>
  isServer() ? 0 : (await db.getFirstAsync<{ n: number }>('SELECT COUNT(*) AS n FROM scans s JOIN trees t ON t.id = s.tree_id WHERE synced = 0 AND t.forest_id = ?', forestId()))?.n ?? 0;

const rank: Record<Status, number> = { infested: 2, watch: 1, healthy: 0, unrated: 0 };
export const dueForRevisit = (trees: TreeRow[]) =>
  trees
    .filter((t) => t.last_scan && Date.now() - t.last_scan > REVISIT_DAYS * DAY)
    .sort((a, b) => rank[b.status!] - rank[a.status!] || a.last_scan! - b.last_scan!);

const insertReading = (db: SQLiteDatabase, treeId: string, scanId: number | null, r: Live) =>
  db.runAsync(`INSERT INTO readings (tree_id, scan_id, created_at, ${READING_COLS}, device) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    treeId, scanId, r.at, r.sensors.soil_moisture_pct, r.sensors.air_temp_c, r.sensors.humidity_pct, r.sensors.light_lux, r.device);

/** A reading on its own (no photos), on the phone. */
export const addLocalReading = (db: SQLiteDatabase, treeId: string, r: Live) => insertReading(db, treeId, null, r);

export async function saveScan(db: SQLiteDatabase, o: {
  treeId?: string; place?: string; coords?: { lat: number; lng: number } | null; photos: string[]; levels: Levels; note: string;
  checks?: Checks; sensors?: Live | null; fingerprints?: { model: string; embeddings: string[] } | null;
}) {
  const now = Date.now();
  // Camera photos live in the cache, which the OS may clear; keep our own copies. (Web photos are data URLs.)
  const photos = Platform.OS === 'web' ? o.photos : await Promise.all(
    o.photos.map(async (uri, i) => {
      const dest = new File(Paths.document, `scan-${now}-${i}.jpg`);
      await new File(uri).copy(dest);
      return dest.uri;
    }),
  );
  let treeId = o.treeId;
  await db.withTransactionAsync(async () => {
    if (!treeId) {
      const max = await db.getFirstAsync<{ n: number | null }>('SELECT MAX(CAST(SUBSTR(id, 3) AS INTEGER)) AS n FROM trees');
      treeId = `H-${String((max?.n ?? 0) + 1).padStart(3, '0')}`;
      await db.runAsync('INSERT INTO trees VALUES (?, ?, ?, ?, ?, ?)', treeId, o.place || 'Unnamed spot', o.coords?.lat ?? null, o.coords?.lng ?? null, now, forestId());
    }
    const { wool, needles, crown, dieback } = o.levels;
    const { signs, severity } = toServer(o.levels, o.checks);
    const { lastInsertRowId: scanId } = await db.runAsync(
      'INSERT INTO scans (tree_id, created_at, photos, wool, needles, crown, dieback, status, note, signs, severity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
      treeId, now, JSON.stringify(photos), wool, needles, crown, dieback, overall(o.levels, o.checks), o.note.trim(), JSON.stringify([...new Set(signs)]), severity);
    if (o.sensors) await insertReading(db, treeId!, scanId, o.sensors);
    for (const [i, e] of (o.fingerprints?.embeddings ?? []).entries())
      await db.runAsync('INSERT INTO fingerprints VALUES (?, ?, ?, ?, ?)', treeId, scanId, i, o.fingerprints!.model, e);
  });
  return treeId!;
}

// A new, empty forest; at: where the user is standing (optional, centers the map).
export async function createForest(db: SQLiteDatabase, name: string, at: { lat: number; lon: number } | null) {
  if (isServer()) {
    const f = await api.createForest(name, at);
    return { id: f.forest_id, name: f.name, lat: f.center?.lat ?? null, lng: f.center?.lon ?? null };
  }
  const r = await db.runAsync('INSERT INTO forests (name, lat, lng) VALUES (?, ?, ?)', name, at?.lat ?? null, at?.lon ?? null);
  return { id: r.lastInsertRowId, name, lat: at?.lat ?? null, lng: at?.lon ?? null };
}

// Deleting cannot be undone; the screens ask the user to type the name first.
export async function deleteForest(db: SQLiteDatabase, f: { id: number; name: string }) {
  if (isServer()) return api.deleteForest(f.id, f.name);
  await db.withTransactionAsync(async () => {
    for (const t of ['readings', 'fingerprints', 'scans']) await db.runAsync(`DELETE FROM ${t} WHERE tree_id IN (SELECT id FROM trees WHERE forest_id = ?)`, f.id);
    await db.runAsync('DELETE FROM trees WHERE forest_id = ?', f.id);
    await db.runAsync('DELETE FROM sections WHERE forest_id = ?', f.id);
    await db.runAsync('DELETE FROM forests WHERE id = ?', f.id);
  });
}

export async function deleteTree(db: SQLiteDatabase, id: string) {
  if (isServer()) return api.deleteTree(id);
  await db.withTransactionAsync(async () => {
    for (const t of ['readings', 'fingerprints', 'scans']) await db.runAsync(`DELETE FROM ${t} WHERE tree_id = ?`, id);
    await db.runAsync('DELETE FROM trees WHERE id = ?', id);
  });
}

// The four signs as the server's checklist, and the severity matching the status shown on the health screen.
// The checklist as the server's sign keys. Insects are only marked "checked, none found" when the
// observer actually looked under the twigs; otherwise they stay "not assessed" on the server.
export function toServer(l: Levels, c: Checks = NO_CHECKS) {
  const twigs = c.twigsChecked
    ? [...(l.wool ? ['hwa_wool'] : []), ...(c.scale ? ['ehs_scale'] : []), ...(!l.wool && !c.scale ? ['twigs_checked_clean'] : [])]
    : [];
  const signs = [
    ...twigs,
    ...(c.banding ? ['needle_yellow_banding'] : []),
    ...(l.needles || l.crown ? ['needle_loss'] : []),
    ...(l.crown ? ['gray_green_foliage'] : []),
    ...(l.dieback ? ['branch_dieback'] : []),
    ...(c.browning ? ['drought_browning'] : []),
    ...(c.borers ? ['borer_holes'] : []),
    ...(c.rootRot ? ['root_rot_signs'] : []),
  ];
  const st = overall(l, c);
  return { signs, severity: st === 'healthy' ? 0 : st === 'watch' ? 1 : Math.max(2, ...Object.values(l)) };
}

// Server mode: the visit was stored when the photos were identified; add the health check and any
// ESP32 readings to it. The server then works out the likely causes (diseases.assess).
// sentWithPhotos: a reading already went to the server with the photos (so dropping it must remove it there).
export async function saveServerVisit(observationId: string, levels: Levels, note: string, c: Checks = NO_CHECKS,
  sensors: api.Sensors | null = null, sentWithPhotos = false) {
  const { signs, severity } = toServer(levels, c);
  await api.setSigns(observationId, [...new Set(signs)]);
  await api.setHealth(observationId, severity, note.trim());
  if (sensors && Object.values(sensors).some((v) => v != null)) await api.setSensors(observationId, sensors);
  else if (sentWithPhotos) await api.clearSensors(observationId); // the user chose not to keep that reading
}

export async function exportCsv(db: SQLiteDatabase) {
  const cell = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  let csv: string;
  if (isServer()) {
    const rows = await listTrees(db);
    const cols = ['id', 'place', 'lat', 'lng', 'last_scan', 'status'] as const;
    csv = [['tree_id', 'condition', 'lat', 'lng', 'last_visit', 'status'].join(','),
      ...rows.map((r) => cols.map((c) => cell(c === 'last_scan' ? new Date(r[c]!).toISOString() : r[c])).join(','))].join('\n');
  } else {
    const rows = await db.getAllAsync<Scan & Tree & api.Sensors>(`SELECT scans.*, place, lat, lng, ${READING_COLS.split(', ').map((c) => `r.${c}`).join(', ')}
      FROM scans JOIN trees ON trees.id = scans.tree_id LEFT JOIN readings r ON r.scan_id = scans.id WHERE trees.forest_id = ? ORDER BY scans.created_at`, forestId());
    const cols = ['tree_id', 'place', 'lat', 'lng', 'created_at', 'wool', 'needles', 'crown', 'dieback', 'status', 'note', 'soil_moisture_pct', 'air_temp_c', 'humidity_pct', 'light_lux'] as const;
    csv = [cols.join(','), ...rows.map((r) => cols.map((c) => cell(c === 'created_at' ? new Date(r[c]).toISOString() : r[c])).join(','))].join('\n');
  }
  const name = `hemlockid-${new Date().toISOString().slice(0, 10)}.csv`;
  if (Platform.OS === 'web') return URL.createObjectURL(new Blob([csv], { type: 'text/csv' })) + '#' + name;
  const file = new File(Paths.cache, name);
  await file.write(csv);
  return file.uri;
}

// Runs a query whenever the screen gains focus, so lists reflect new scans.
// Also reruns when the forest or account changes. A failed server call keeps the previous data.
/** The last load that failed (e.g. no server while on the sensor unit's Wi-Fi); `retry` reloads every screen's data. */
export const useLoadError = create<{ error: string | null; attempt: number; retry(): void }>((set) => ({
  error: null,
  attempt: 0,
  retry: () => set((s) => ({ error: null, attempt: s.attempt + 1 })),
}));

export function useQuery<T>(fn: (db: SQLiteDatabase) => Promise<T>, key = '') {
  const db = useDb();
  const scope = useSession((s) => `${s.mode}:${s.token}:${s.forest?.id}`);
  const attempt = useLoadError((s) => s.attempt);
  const [data, setData] = useState<T>();
  useFocusEffect(
    useCallback(() => {
      let live = true;
      fn(db).then(
        (d) => {
          if (!live) return;
          setData(d);
          if (useLoadError.getState().error) useLoadError.setState({ error: null });
        },
        (e: Error) => live && useLoadError.setState({ error: e.message }),
      );
      return () => void (live = false);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [db, key, scope, attempt]),
  );
  return data;
}

export const ago = (t: number | null) => {
  if (!t) return 'Never scanned';
  const d = Math.floor((Date.now() - t) / DAY);
  return d === 0 ? 'Today' : d === 1 ? 'Yesterday' : `${d} days ago`;
};
export const fmtDate = (t: number) => new Date(t).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
