// Live check of the client against a running server.
//   node test/live.mjs [tree photos...]
// With 6 photos of ONE tree: enrols the first 3, revisits with the last 3 (expects the same ID).
// Env: HEMLOCK_URL (default http://localhost:8000), HEMLOCK_API_KEY,
//      HEMLOCK_EMAIL / HEMLOCK_PASSWORD (default: the demo account).
import { readFileSync } from "node:fs";
import { basename } from "node:path";
import { HemlockClient, HemlockApiError } from "../dist/index.js";

const api = new HemlockClient({ baseUrl: process.env.HEMLOCK_URL ?? "http://localhost:8000", apiKey: process.env.HEMLOCK_API_KEY });
const photos = process.argv.slice(2).map((p) => new File([readFileSync(p)], basename(p), { type: "image/jpeg" }));
const ok = (cond, msg) => { if (!cond) { console.error("FAIL:", msg); process.exit(1); } console.log("ok  ", msg); };

const h = await api.health();
ok(h.status === "ok", `health: model ${h.model_version}${h.demo ? " (DEMO)" : ""}`);
const login = await api.login(process.env.HEMLOCK_EMAIL ?? "demo@hemlock.test", process.env.HEMLOCK_PASSWORD ?? "hemlock-demo");
ok(!!login.token, `signed in as ${login.user.name}`);
const me = await api.me();
ok(Array.isArray(me.forests), `account: ${me.totals.forests} forests, ${me.totals.trees} trees (${me.forests.map((f) => f.name).join("; ")})`);
const forest = await api.createForest(`Live test ${new Date().toISOString()}`, { lat: 34.75, lon: -84.12 });
api.setForest(forest.forest_id);
ok(forest.tree_count === 0, `new forest #${forest.forest_id}: ${forest.name}`);
const p = await api.protocol();
ok(p.min_views === 3, `protocol: ${p.views.map((v) => v.key).join(" -> ")}`);
try { await api.getTree("NOPE-1"); ok(false, "404 expected"); }
catch (e) { ok(e instanceof HemlockApiError && e.code === "tree_not_found", `typed error: ${e.code}`); }

if (photos.length >= 6) {
  const cap = await api.createCapture();
  for (const f of photos.slice(0, 3)) {
    const v = await api.addView(cap.capture_id, f);
    ok(v.view.accepted, `guided view ${v.view.view_type} accepted (next: ${v.next_view?.key})`);
  }
  const first = await api.identifyCapture(cap.capture_id, { location: { lat: 34.75, lon: -84.12, accuracy_m: 5 }, severity: 1 });
  ok(first.observation_id != null, `enrol: ${first.status} ${first.tree_id ?? ""} species=${first.species?.name} ${first.species?.confidence}`);
  const again = await api.identify(photos.slice(3, 6), { location: { lat: 34.75, lon: -84.12 }, severity: 2, healthNotes: "more wool" });
  ok(again.candidates[0]?.tree_id === first.tree_id,
     `revisit (one-shot, different photos): ${again.status} ${again.tree_id ?? ""} p=${again.probability} action=${again.action} top=${again.candidates.map((c) => c.tree_id).join(",")}`);
  const t = await api.getTree(first.tree_id);
  ok(t.observation_count >= 1, `tree ${t.tree_id}: ${t.observation_count} observation(s), thumbnail ${t.thumbnail_url ? "yes" : "no"}`);
  ok(t.severity === 2 && t.observations.map((o) => o.severity).join() === "1,2", `severity history: ${t.observations.map((o) => o.severity).join(" -> ")}`);
  const m = await api.forestMap();
  ok(m.features.length === 1 && m.features[0].properties.severity_label === "moderate", `map: ${m.features.length} tree(s), ${JSON.stringify(m.features[0].geometry.coordinates)} ${m.features[0].properties.severity_label}`);
  const src = api.imageSource(t.thumbnail_url);
  const img = await fetch(src.uri, { headers: src.headers });
  ok(img.ok && img.headers.get("content-type") === "image/jpeg", `thumbnail served (${(await img.arrayBuffer()).byteLength} bytes)`);
  const q = await api.reviewQueue();
  console.log(`     review queue: ${q.total} uncertain`);
}
const trees = await api.listTrees();
ok(Array.isArray(trees.items), `trees in database: ${trees.total}`);
await api.logout();
try { await api.me(); ok(false, "signed out"); } catch (e) { ok(e.code === "not_signed_in", "signed out"); }
console.log("ALL OK");
