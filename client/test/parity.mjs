// On-device engine vs server, same photos, same model:   node test/parity.mjs test/fixture.json
// (make the fixture with: python scripts/ondevice_parity_fixture.py --out client/test/fixture.json)
import { readFileSync } from "node:fs";
import * as ort from "onnxruntime-node";
import jpeg from "jpeg-js";
import { OnDeviceModel } from "../dist/ondevice.js";

const fx = JSON.parse(readFileSync(process.argv[2] ?? "test/fixture.json", "utf8"));
const model = await OnDeviceModel.create(ort, readFileSync(fx.model), fx.meta, fx.calibration, {});
const KEYS = ["trunk_north", "trunk_right", "trunk_right2"];
const cos = (a, b) => { let d = 0, na = 0, nb = 0; for (let i = 0; i < a.length; i++) { d += a[i] * b[i]; na += a[i] ** 2; nb += b[i] ** 2; } return d / Math.sqrt(na * nb); };

let same = 0, n = 0, minCos = 1, accMismatch = 0, ms = [];
const rows = [];
for (const q of fx.queries) {
  const views = [];
  for (const [i, p] of q.paths.entries()) {
    const img = jpeg.decode(readFileSync(p), { useTArray: true, maxMemoryUsageInMB: 1024 });
    const v = await model.processView({ width: img.width, height: img.height, data: img.data, channels: 4 }, KEYS[i], views);
    views.push(v); ms.push(v.ms);
    const ref = q.views[i];
    if (v.accepted !== ref.accepted) accMismatch++;
    if (v.embedding && ref.embedding) minCos = Math.min(minCos, cos(v.embedding, ref.embedding));
  }
  const r = model.identify(views, fx.gallery);
  const ok = r.status === q.server.status && r.tree_id === q.server.tree_id;
  same += ok; n++;
  rows.push(`${ok ? "same" : "DIFF"}  ${q.tree.padEnd(10)} truth=${String(q.truth).padEnd(6)} server=${q.server.status}/${q.server.tree_id ?? "-"} p=${q.server.probability?.toFixed(3) ?? "-"}  device=${r.status}/${r.tree_id ?? "-"} p=${r.probability?.toFixed(3) ?? "-"}`);
}
console.log(rows.join("\n"));
const summary = { decisions_identical: `${same}/${n}`, min_embedding_cosine: +minCos.toFixed(5),
  quality_accept_mismatches: accMismatch, mean_ms_per_view: Math.round(ms.reduce((a, b) => a + b, 0) / ms.length) };
console.log(JSON.stringify(summary));
if (same < n || minCos < 0.98) process.exit(1);
