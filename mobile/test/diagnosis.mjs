// Runs the phone's diagnosis (src/diagnosis.ts) on JSON cases from stdin (one per line) and prints one JSON
// result per line. tests/integration/test_phone_diagnosis.py compares it with the backend's Python rules.
import { readFileSync } from "node:fs";
const d = await import("../src/diagnosis.ts");
for (const line of readFileSync(0, "utf8").split("\n").filter(Boolean)) {
  const c = JSON.parse(line);
  if (c.kind === "assess") {
    console.log(JSON.stringify(d.assess(c.signs, c.sensors, c.severity, c.when, c.has_images, c.ai)));
  } else {
    const visits = c.visits.map((v) => ({ ...v, findings: d.assess(v.signs, v.sensors, v.severity, v.at, false, null) }));
    const hist = d.sensorHistory(visits), env = d.environment(hist), cur = d.currentConditions(visits);
    console.log(JSON.stringify({ env, since: d.sinceLastVisit(visits), next: d.nextAction(visits, cur, env), current: cur.map((f) => f.condition) }));
  }
}
