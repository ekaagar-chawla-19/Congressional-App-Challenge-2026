// A full-size camera photo through the phone's decode path (src/engine/index.ts decode(): shrink natively by the
// server's JPEG draft factor, then decode), vs the server's own decode. argv: photo.jpg reference.json
// The native shrink is emulated with the engine's area resize. Prints one JSON object (test_phone_engine.py).
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../../client/package.json", import.meta.url));
const ort = require("onnxruntime-node"), jpeg = require("jpeg-js");
const root = new URL("../../", import.meta.url);
const { OnDeviceModel, resizeArea } = await import("../src/engine/ondevice.ts");
const m = await OnDeviceModel.create(ort, readFileSync(new URL("models/production/hemlock.onnx", root)),
  JSON.parse(readFileSync(new URL("models/production/hemlock.json", root))), JSON.parse(readFileSync(new URL("models/production/calibration.json", root))), {});
const ref = JSON.parse(readFileSync(process.argv[3]));
const full = jpeg.decode(readFileSync(process.argv[2]), { useTArray: true, formatAsRGBA: false, maxMemoryUsageInMB: 2048 });
let s = 1; // same rule as decode() in src/engine/index.ts
while (s < 8 && Math.floor(Math.min(full.width, full.height) / (s * 2)) >= 640) s *= 2;
const w = Math.floor(full.width / s), h = Math.floor(full.height / s);
const v = await m.processView({ width: w, height: h, data: resizeArea(full.data, full.width, full.height, 3, w, h), channels: 3 }, "trunk_north", []);
let d = 0, n = 0;
v.embedding.forEach((x, i) => { d += x * ref.embedding[i]; n += x * x; });
console.log(JSON.stringify({ size: [w, h], server_size: ref.size, cosine: d / Math.sqrt(n) }));
