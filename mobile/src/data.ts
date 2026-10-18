import { File, Paths } from 'expo-file-system';
import { useFocusEffect } from 'expo-router';
import { useSQLiteContext, type SQLiteDatabase } from 'expo-sqlite';
import { useCallback, useState } from 'react';
import { Platform } from 'react-native';
import * as api from './api';
import { isServer, useSession } from './session';
import type { Status } from './theme';

export type Tree = { id: string; place: string; lat: number | null; lng: number | null; created_at: number };
// conditions: likelihood 0-1 per condition (server only).
export type TreeRow = Tree & { status: Status | null; last_scan: number | null; photo: string | null; conditions?: Record<string, number> };
export type Scan = { id: number; tree_id: string; created_at: number; photos: string; status: Status; note: string; synced: number } & Levels;
export type Forest = { id: number; name: string; lat: number | null; lng: number | null; trees: number; counts: Record<Status, number>; last_visit: number | null };
// Extra detail only the server has: disease assessment and the ESP32 reading of the latest visit.
// history: per visit (oldest first), the likelihood of each condition assessed on that visit.
export type TreeExtras = { conditions: api.Finding[]; sensors: api.Sensors | null; history: { at: number; c: Record<string, number> }[] };

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
export const overall = (l: Levels): Status => {
  const worst = Math.max(...Object.values(l));
  return l.wool >= 2 || worst >= 3 ? 'infested' : worst >= 1 ? 'watch' : 'healthy';
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
          await db.runAsync(
            'INSERT INTO scans (tree_id, created_at, photos, wool, needles, crown, dieback, status, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)',
            id, at, '[]', l.wool, l.needles, l.crown, l.dieback, overall(l));
        }
      }
    }
  });
}

const forestId = () => useSession.getState().forest?.id ?? -1;
const ms = (iso: string | null) => (iso ? Date.parse(iso) : null);
// Server severity 0-3 (observer rating) to the app's status.
const statusOf = (sev: number | null): Status => (sev == null ? 'unrated' : sev === 0 ? 'healthy' : sev === 1 ? 'watch' : 'infested');
const conditionLabel = (t: api.TreeSummary) =>
  ({ hwa: 'Woolly adelgid', ehs: 'Elongate hemlock scale', drought_stress: 'Drought stress' } as Record<string, string>)[t.main_condition ?? ''] ??
  (t.severity === 0 ? 'No problems found' : 'No condition confirmed');

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

// Each tree with its latest scan.
const LIST_SQL = `
    SELECT t.*, s.status, s.created_at AS last_scan, json_extract(s.photos, '$[0]') AS photo
    FROM trees t LEFT JOIN scans s ON s.id = (SELECT id FROM scans WHERE tree_id = t.id ORDER BY created_at DESC LIMIT 1)
    WHERE t.forest_id = ? ORDER BY s.created_at DESC`;

export async function listTrees(db: SQLiteDatabase): Promise<TreeRow[]> {
  if (!isServer()) return db.getAllAsync<TreeRow>(LIST_SQL, forestId());
  return (await api.trees()).map((t) => ({
    id: t.tree_id, place: conditionLabel(t), lat: t.location?.lat ?? null, lng: t.location?.lon ?? null, created_at: Date.parse(t.created_at),
    status: statusOf(t.severity), last_scan: Date.parse(t.last_seen_at), photo: api.absolute(t.thumbnail_url),
    conditions: Object.fromEntries(Object.entries(t.conditions ?? {}).map(([k, f]) => [k, f.likelihood])),
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
    return {
      tree: await db.getFirstAsync<Tree>('SELECT * FROM trees WHERE id = ?', id),
      scans: await db.getAllAsync<Scan>('SELECT * FROM scans WHERE tree_id = ? ORDER BY created_at DESC', id),
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
      conditions: t.current_conditions, sensors: t.latest_sensors,
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

export async function saveScan(db: SQLiteDatabase, o: { treeId?: string; place?: string; coords?: { lat: number; lng: number } | null; photos: string[]; levels: Levels; note: string }) {
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
    await db.runAsync(
      'INSERT INTO scans (tree_id, created_at, photos, wool, needles, crown, dieback, status, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
      treeId, now, JSON.stringify(photos), wool, needles, crown, dieback, overall(o.levels), o.note.trim());
  });
  return treeId!;
}

// The four signs as the server's checklist, and the severity matching the status shown on the health screen.
export function toServer(l: Levels) {
  const signs = [
    l.wool ? 'hwa_wool' : 'twigs_checked_clean',
    ...(l.needles || l.crown ? ['needle_loss'] : []),
    ...(l.crown ? ['gray_green_foliage'] : []),
    ...(l.dieback ? ['branch_dieback'] : []),
  ];
  const st = overall(l);
  return { signs, severity: st === 'healthy' ? 0 : st === 'watch' ? 1 : Math.max(2, ...Object.values(l)) };
}

// Server mode: the visit was stored when the photos were identified; add the health check to it.
export async function saveServerVisit(observationId: string, levels: Levels, note: string) {
  const { signs, severity } = toServer(levels);
  await api.setSigns(observationId, [...new Set(signs)]);
  await api.setHealth(observationId, severity, note.trim());
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
    const rows = await db.getAllAsync<Scan & Tree>('SELECT scans.*, place, lat, lng FROM scans JOIN trees ON trees.id = scans.tree_id WHERE trees.forest_id = ? ORDER BY scans.created_at', forestId());
    const cols = ['tree_id', 'place', 'lat', 'lng', 'created_at', 'wool', 'needles', 'crown', 'dieback', 'status', 'note'] as const;
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
export function useQuery<T>(fn: (db: SQLiteDatabase) => Promise<T>, key = '') {
  const db = useSQLiteContext();
  const scope = useSession((s) => `${s.mode}:${s.token}:${s.forest?.id}`);
  const [data, setData] = useState<T>();
  useFocusEffect(
    useCallback(() => {
      let live = true;
      fn(db).then((d) => live && setData(d), (e: Error) => console.warn(e.message));
      return () => void (live = false);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [db, key, scope]),
  );
  return data;
}

export const ago = (t: number | null) => {
  if (!t) return 'Never scanned';
  const d = Math.floor((Date.now() - t) / DAY);
  return d === 0 ? 'Today' : d === 1 ? 'Yesterday' : `${d} days ago`;
};
export const fmtDate = (t: number) => new Date(t).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
