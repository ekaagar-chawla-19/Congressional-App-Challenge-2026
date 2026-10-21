// Parses ESP32 reading lines from stdin ("name<TAB>json" per line) with the phone app's parser
// (src/esp32reading.ts, run by Node's TypeScript type stripping) and prints "name<TAB>result-json".
// Used by tests/integration/test_esp32_simulated.py: the app must read the firmware's real output exactly
// like the backend does.
import { readFileSync } from "node:fs";
import { parseEsp32Reading } from "../src/esp32reading.ts";

for (const line of readFileSync(0, "utf8").split("\n").filter(Boolean)) {
  const [name, json] = line.split("\t");
  let out;
  try {
    out = parseEsp32Reading(json);
  } catch (e) {
    out = { error: String(e.message ?? e) };
  }
  console.log(`${name}\t${JSON.stringify(out)}`);
}
