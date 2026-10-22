// Copies Model Delta (models/production) into the app's assets so a development build can run it on the phone.
// The 87 MB .onnx file is not committed twice: assets/models/hemlock.onnx is git-ignored and recreated here
// (runs after npm install). The two small JSON files are committed so the app always type-checks.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const from = join(root, "..", "models", "production");
const to = join(root, "assets", "models");
mkdirSync(to, { recursive: true });
for (const f of ["hemlock.onnx", "hemlock.json", "calibration.json"]) {
  if (existsSync(join(from, f))) copyFileSync(join(from, f), join(to, f));
  else console.warn(`copy-models: ${join(from, f)} missing; the on-device model will not be available`);
}
console.log(`copy-models: Model Delta -> ${to}`);
