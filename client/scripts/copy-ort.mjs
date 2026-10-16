// Copy the onnxruntime-web WebAssembly build next to the web app, so phones load it from the backend
// (no CDN needed in the field).
import { copyFileSync, mkdirSync } from "node:fs";
const src = "node_modules/onnxruntime-web/dist/", dst = "../src/hemlock_sentinel/api/static/ort/";
mkdirSync(dst, { recursive: true });
for (const f of ["ort.wasm.min.js", "ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm"]) copyFileSync(src + f, dst + f);
console.log("copied onnxruntime-web to", dst);
