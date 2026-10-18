import { File, Paths } from 'expo-file-system';
import { useFocusEffect } from 'expo-router';
import { useSQLiteContext, type SQLiteDatabase } from 'expo-sqlite';
import { useCallback, useState } from 'react';
import type { Status } from './theme';

export type Tree = { id: string; place: string; lat: number | null; lng: number | null; created_at: number };
export type TreeRow = Tree & { status: Status | null; last_scan: number | null; photo: string | null };
export type Scan = { id: number; tree_id: string; created_at: number; photos: string; status: Status; note: string; synced: number } & Levels;

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
  if (__DEV__ && !(await db.getFirstAsync('SELECT 1 FROM trees'))) await seed(db);
}

// Sample trees for development builds only.
async function seed(db: SQLiteDatabase) {
  const now = Date.now();
  const rows: [string, string, number, number, number, Levels][] = [
    ['H-001', 'Ridge Trail', 41.3341, -79.2123, 0, { wool: 0, needles: 0, crown: 0, dieback: 0 }],
    ['H-002', 'Ridge Trail', 41.3352, -79.2101, 94, { wool: 2, needles: 2, crown: 1, dieback: 1 }],
    ['H-003', 'Creek Bend', 41.3329, -79.2087, 61, { wool: 1, needles: 1, crown: 0, dieback: 0 }],
    ['H-004', 'North Slope', 41.3367, -79.2142, 12, { wool: 0, needles: 0, crown: 0, dieback: 0 }],
    ['H-005', 'Overlook', 41.3318, -79.2131, 45, { wool: 3, needles: 2, crown: 2, dieback: 1 }],
  ];
  await db.withTransactionAsync(async () => {
    for (const [id, place, lat, lng, ago, l] of rows) {
      const at = now - ago * DAY;
      await db.runAsync('INSERT INTO trees VALUES (?, ?, ?, ?, ?)', id, place, lat, lng, at - 120 * DAY);
      await db.runAsync(
        'INSERT INTO scans (tree_id, created_at, photos, wool, needles, crown, dieback, status, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)',
        id, at, '[]', l.wool, l.needles, l.crown, l.dieback, overall(l));
    }
  });
}

// Each tree with its latest scan.
export const listTrees = (db: SQLiteDatabase) =>
  db.getAllAsync<TreeRow>(`
    SELECT t.*, s.status, s.created_at AS last_scan, json_extract(s.photos, '$[0]') AS photo
    FROM trees t LEFT JOIN scans s ON s.id = (SELECT id FROM scans WHERE tree_id = t.id ORDER BY created_at DESC LIMIT 1)
    ORDER BY s.created_at DESC`);

export const getTree = async (db: SQLiteDatabase, id: string) => ({
  tree: await db.getFirstAsync<Tree>('SELECT * FROM trees WHERE id = ?', id),
  scans: await db.getAllAsync<Scan>('SELECT * FROM scans WHERE tree_id = ? ORDER BY created_at DESC', id),
});

export const pendingCount = async (db: SQLiteDatabase) =>
  (await db.getFirstAsync<{ n: number }>('SELECT COUNT(*) AS n FROM scans WHERE synced = 0'))?.n ?? 0;

const rank: Record<Status, number> = { infested: 2, watch: 1, healthy: 0 };
export const dueForRevisit = (trees: TreeRow[]) =>
  trees
    .filter((t) => t.last_scan && Date.now() - t.last_scan > REVISIT_DAYS * DAY)
    .sort((a, b) => rank[b.status!] - rank[a.status!] || a.last_scan! - b.last_scan!);

export async function saveScan(db: SQLiteDatabase, o: { treeId?: string; place?: string; coords?: { lat: number; lng: number } | null; photos: string[]; levels: Levels; note: string }) {
  const now = Date.now();
  // Camera photos live in the cache, which the OS may clear; keep our own copies.
  const photos = await Promise.all(
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
      await db.runAsync('INSERT INTO trees VALUES (?, ?, ?, ?, ?)', treeId, o.place || 'Unnamed spot', o.coords?.lat ?? null, o.coords?.lng ?? null, now);
    }
    const { wool, needles, crown, dieback } = o.levels;
    await db.runAsync(
      'INSERT INTO scans (tree_id, created_at, photos, wool, needles, crown, dieback, status, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
      treeId, now, JSON.stringify(photos), wool, needles, crown, dieback, overall(o.levels), o.note.trim());
  });
  return treeId!;
}

export async function exportCsv(db: SQLiteDatabase) {
  const rows = await db.getAllAsync<Scan & Tree>('SELECT scans.*, place, lat, lng FROM scans JOIN trees ON trees.id = scans.tree_id ORDER BY scans.created_at');
  const cols = ['tree_id', 'place', 'lat', 'lng', 'created_at', 'wool', 'needles', 'crown', 'dieback', 'status', 'note'] as const;
  const cell = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const csv = [cols.join(','), ...rows.map((r) => cols.map((c) => cell(c === 'created_at' ? new Date(r[c]).toISOString() : r[c])).join(','))].join('\n');
  const file = new File(Paths.cache, `hemlockid-${new Date().toISOString().slice(0, 10)}.csv`);
  await file.write(csv);
  return file.uri;
}

// Runs a query whenever the screen gains focus, so lists reflect new scans.
export function useQuery<T>(fn: (db: SQLiteDatabase) => Promise<T>, key = '') {
  const db = useSQLiteContext();
  const [data, setData] = useState<T>();
  useFocusEffect(
    useCallback(() => {
      let live = true;
      fn(db).then((d) => live && setData(d));
      return () => void (live = false);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [db, key]),
  );
  return data;
}

export const ago = (t: number | null) => {
  if (!t) return 'Never scanned';
  const d = Math.floor((Date.now() - t) / DAY);
  return d === 0 ? 'Today' : d === 1 ? 'Yesterday' : `${d} days ago`;
};
export const fmtDate = (t: number) => new Date(t).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
