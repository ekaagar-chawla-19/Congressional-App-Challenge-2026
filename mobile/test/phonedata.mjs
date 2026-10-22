// The phone-only data layer (src/data.ts) on a real SQLite database (Node's built-in node:sqlite behind the
// expo-sqlite async API): migrations, saving scans with checklist + sensor reading + fingerprints, readings on their
// own, and the diagnosis worked out on the phone. Prints one JSON object (tests/integration/test_phone_data.py).
import { DatabaseSync } from "node:sqlite";

const wrap = (raw) => ({
  execAsync: async (sql) => raw.exec(sql),
  runAsync: async (sql, ...a) => { const r = raw.prepare(sql).run(...a.map((x) => x ?? null)); return { lastInsertRowId: Number(r.lastInsertRowid), changes: r.changes }; },
  getAllAsync: async (sql, ...a) => raw.prepare(sql).all(...a.map((x) => x ?? null)),
  getFirstAsync: async (sql, ...a) => raw.prepare(sql).get(...a.map((x) => x ?? null)) ?? null,
  withTransactionAsync: async (fn) => { raw.exec("BEGIN"); try { await fn(); raw.exec("COMMIT"); } catch (e) { raw.exec("ROLLBACK"); throw e; } },
});

const data = await import("../src/data.ts");
const { useSession } = await import("../src/session.ts");
const out = {};

// 1. An existing v2 phone (forests + trees + scans from before) upgrades in place.
const old = new DatabaseSync(":memory:");
old.exec(`CREATE TABLE trees (id TEXT PRIMARY KEY, place TEXT NOT NULL, lat REAL, lng REAL, created_at INTEGER NOT NULL, forest_id INTEGER);
  CREATE TABLE scans (id INTEGER PRIMARY KEY AUTOINCREMENT, tree_id TEXT NOT NULL, created_at INTEGER NOT NULL, photos TEXT NOT NULL,
    wool INTEGER, needles INTEGER, crown INTEGER, dieback INTEGER, status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', synced INTEGER NOT NULL DEFAULT 0);
  CREATE TABLE forests (id INTEGER PRIMARY KEY, name TEXT NOT NULL, lat REAL, lng REAL);
  INSERT INTO forests VALUES (1, 'Old forest', NULL, NULL);
  INSERT INTO trees VALUES ('H-001', 'Creek', NULL, NULL, 1, 1);
  INSERT INTO scans (tree_id, created_at, photos, wool, needles, crown, dieback, status) VALUES ('H-001', 2, '[]', 0, 1, 0, 0, 'watch');
  PRAGMA user_version = 2;`);
await data.migrate(wrap(old));
useSession.setState({ mode: "local", forest: { id: 1, name: "Old forest", lat: null, lng: null } });
out.upgraded = { version: old.prepare("PRAGMA user_version").get().user_version, trees: (await data.listTrees(wrap(old))).map((t) => [t.id, t.status, t.sensors]),
  signs: JSON.parse(old.prepare("SELECT signs FROM scans").get().signs), severity: old.prepare("SELECT severity FROM scans").get().severity,
  conditions: (await data.getTree(wrap(old), "H-001")).extras.conditions.map((c) => [c.condition, c.level]) };

// 2. A new phone: demo forests get sensor readings; the phone works out conditions and sensors per tree.
const raw = new DatabaseSync(":memory:");
const db = wrap(raw);
await data.migrate(db);
await data.seedDemo(db);
const demoForest = raw.prepare("SELECT id FROM forests WHERE name = 'Cloudland Canyon State Park'").get().id;
useSession.setState({ forest: { id: demoForest, name: "Cloudland", lat: null, lng: null } });
const demo = await data.listTrees(db);
out.demo = { trees: demo.length, with_sensors: demo.filter((t) => t.sensors).length, with_conditions: demo.filter((t) => Object.keys(t.conditions ?? {}).length).length,
  readings: raw.prepare("SELECT COUNT(*) n FROM readings").get().n };

// Insights on the phone: the forest, a saved section, and the section gone again.
const forestA = await data.forestAnalysis(db);
const located = demo.filter((t) => t.lat != null);
const box = [Math.min(...located.map((t) => t.lng)), Math.min(...located.map((t) => t.lat)), Math.max(...located.map((t) => t.lng)), Math.max(...located.map((t) => t.lat))];
const sec = await data.createSection(db, "Whole stand", box);
let dup = null;
await data.createSection(db, "whole stand", box).catch((e) => (dup = e.message));
const secA = await data.sectionAnalysis(db, sec.section_id);
const secList = (await data.forestAnalysis(db)).sections.map((s) => [s.name, s.trees]);
await data.deleteSection(db, sec.section_id);
out.insights = { trees: forestA.summary.trees, trends: forestA.trends.length, worst: forestA.worst_trees.length, recs: forestA.summary.recommendations.length,
  section_trees: secA.summary.trees, section_name: secA.section.name, located: located.length, listed: secList, dup,
  after_delete: (await data.forestAnalysis(db)).sections.length };

// 3. A scan saved on the phone: checklist + reading + fingerprints, then a reading on its own two weeks later.
const f = await data.createForest(db, "Test stand", null);
useSession.setState({ forest: { id: f.id, name: f.name, lat: null, lng: null } });
const levels = { wool: 2, needles: 1, crown: 0, dieback: 0 };
const checks = { ...data.NO_CHECKS, twigsChecked: true };
const dry = { device: "HS-ESP32-1C49", at: Date.now(), sensors: { soil_moisture_pct: 11, air_temp_c: 31, humidity_pct: 25, light_lux: 6000 } };
const id = await data.saveScan(db, { place: "Ridge", photos: [], levels, note: "first", checks, sensors: dry, fingerprints: { model: "m1", embeddings: ["AAAA", "BBBB", "CCCC"] } });
const camOnly = await data.saveScan(db, { place: "No unit", photos: [], levels: { wool: 0, needles: 0, crown: 0, dieback: 0 }, note: "", checks: data.NO_CHECKS, sensors: null });
const first = await data.getTree(db, id);
await data.addLocalReading(db, id, { device: "HS-ESP32-1C49", at: Date.now() + 14 * 86400000, sensors: { soil_moisture_pct: 40, air_temp_c: 18, humidity_pct: 70, light_lux: null } });
const after = await data.getTree(db, id);
const cam = await data.getTree(db, camOnly);
const listed = await data.listTrees(db);
out.scan = {
  id, signs: JSON.parse(raw.prepare("SELECT signs FROM scans WHERE tree_id = ?").get(id).signs), severity: raw.prepare("SELECT severity FROM scans WHERE tree_id = ?").get(id).severity,
  fingerprints: raw.prepare("SELECT COUNT(*) n FROM fingerprints WHERE tree_id = ?").get(id).n,
  first: { conditions: first.extras.conditions.map((c) => [c.condition, c.level]), sensors: first.extras.sensors, env: first.extras.environment?.summary, next: first.extras.next },
  after: { conditions: after.extras.conditions.map((c) => [c.condition, c.level]), readings: after.extras.readings.length, sensors: after.extras.sensors,
    env: after.extras.environment, changes: after.extras.changes },
  camera_only: { sensors: cam.extras.sensors, readings: cam.extras.readings.length, conditions: cam.extras.conditions.map((c) => c.condition) },
  // by ID: the two scans can share a millisecond, which leaves their "latest first" order open
  listed: [...listed].sort((a, b) => (a.id < b.id ? -1 : 1)).map((t) => ({ id: t.id, sensors: t.sensors, conditions: t.conditions })),
};
await data.deleteTree(db, id);
out.deleted = { readings: raw.prepare("SELECT COUNT(*) n FROM readings WHERE tree_id = ?").get(id).n, fingerprints: raw.prepare("SELECT COUNT(*) n FROM fingerprints WHERE tree_id = ?").get(id).n };
console.log(JSON.stringify(out));
