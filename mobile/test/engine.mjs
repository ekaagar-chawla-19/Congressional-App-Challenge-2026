// The app's on-device engine (src/engine/ondevice.ts + codec.ts) under Node with onnxruntime-node, on the photo the
// server recorded in web/speedtest/reference.json. Prints one JSON object (tests/integration/test_phone_engine.py).
// The phone decodes photos to at most 1280 px on the short side first; this 1200x1600 photo is already below that,
// so these are exactly the pixels the phone feeds the model.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(new URL("../../client/package.json", import.meta.url));
const ort = require("onnxruntime-node");
const jpeg = require("jpeg-js");
const { OnDeviceModel, decodeEmbedding } = await import("../src/engine/ondevice.ts");
const { encodeEmbedding, bytesFromBase64 } = await import("../src/engine/codec.ts");

const root = new URL("../../", import.meta.url);
const ref = JSON.parse(readFileSync(new URL("web/speedtest/reference.json", root), "utf8"));
const meta = JSON.parse(readFileSync(new URL("models/production/hemlock.json", root), "utf8"));
const cal = JSON.parse(readFileSync(new URL("models/production/calibration.json", root), "utf8"));
const model = await OnDeviceModel.create(ort, readFileSync(new URL("models/production/hemlock.onnx", root)), meta, cal, {});

const jpg = readFileSync(new URL("web/speedtest/sample.jpg", root));
// same decode as the phone: base64 (as expo-image-manipulator returns it) -> bytes -> jpeg-js RGB
const b64 = jpg.toString("base64");
// Hermes (the phone's JavaScript engine) has no Buffer: decode without it, like the phone does
const NodeBuffer = globalThis.Buffer;
delete globalThis.Buffer;
const bytes = bytesFromBase64(b64);
const img = jpeg.decode(bytes, { useTArray: true, formatAsRGBA: false });
globalThis.Buffer = NodeBuffer;
const v = await model.processView({ width: img.width, height: img.height, data: img.data, channels: 3 }, "trunk_north", []);

const e = Array.from(v.embedding ?? []), r = ref.delta.embedding;
const norm = (a) => Math.sqrt(a.reduce((s, x) => s + x * x, 0));
const cos = e.length ? e.reduce((s, x, i) => s + x * r[i], 0) / (norm(e) * norm(r)) : null;
const l = Array.from(v.speciesLogits ?? []), mx = Math.max(...l), ex = l.map((x) => Math.exp(x - mx));
const hemlock = ex.length ? ex[meta.species_labels.indexOf("tsuga_canadensis")] / ex.reduce((a, b) => a + b, 0) : null;
const round = Array.from(decodeEmbedding(encodeEmbedding(new Float32Array(e))));

console.log(JSON.stringify({
  decoded: [img.width, img.height], accepted: v.accepted, problems: v.problems, cosine: cos,
  hemlock, hemlock_ref: ref.delta.hemlock_probability, codec_roundtrip_exact: round.length === e.length && round.every((x, i) => x === Math.fround(e[i])),
  ms: v.ms,
}));
