// Parses ESP32 reading lines from stdin ("name<TAB>json" per line) with the app's parser and prints
// "name<TAB>result-json". Used by tests/integration/test_esp32_simulated.py to check the TypeScript
// parser gives the same answers as the Python one on the firmware's real output.
import { readFileSync } from "node:fs";
import { parseEsp32Reading } from "../dist/esp32.js";

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
