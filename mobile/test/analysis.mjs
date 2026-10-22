// Runs the phone's forest analysis (src/analysis.ts) on JSON cases from stdin (one per line) and prints one JSON
// result per line. tests/integration/test_phone_analysis.py compares it with the backend's Python (api/analysis.py).
import { readFileSync } from "node:fs";
const d = await import("../src/diagnosis.ts");
const a = await import("../src/analysis.ts");
for (const line of readFileSync(0, "utf8").split("\n").filter(Boolean)) {
  const c = JSON.parse(line);
  const trees = c.trees.map((t) => ({ ...t, visits: t.visits.map((v) => ({ ...v, findings: d.assess(v.signs, v.sensors, v.severity, v.at, v.has_images, null) })) }));
  const out = a.analyze(trees, c.sections, c.bbox);
  console.log(JSON.stringify({ ...out, round: c.round?.map(([x, n]) => a.pyRound(x, n)) }));
}
