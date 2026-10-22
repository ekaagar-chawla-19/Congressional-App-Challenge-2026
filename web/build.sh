#!/usr/bin/env bash
# Assemble the GitHub Pages site: web/ + both models + ONNX Runtime Web.  Usage: bash web/build.sh [OUT_DIR]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/_site}"
ORT_VERSION=1.30.0

rm -rf "$OUT"
mkdir -p "$OUT"
cp -R "$ROOT/web/." "$OUT/"
rm -f "$OUT/build.sh"

mkdir -p "$OUT/models/delta" "$OUT/models/gamma"
cp "$ROOT/models/production/hemlock.onnx" "$OUT/models/delta/model.onnx"
cp "$ROOT/models/production/hemlock.json" "$OUT/models/delta/model.json"
cp "$ROOT/models/production/calibration.json" "$OUT/models/delta/calibration.json"
cp "$ROOT/models/gamma/gamma.onnx" "$OUT/models/gamma/model.onnx"
cp "$ROOT/models/gamma/gamma.json" "$OUT/models/gamma/model.json"
cp "$ROOT/models/gamma/calibration.json" "$OUT/models/gamma/calibration.json"

TMP="$(mktemp -d)"
(cd "$TMP" && npm pack "onnxruntime-web@$ORT_VERSION" --silent >/dev/null && tar xzf onnxruntime-web-*.tgz)
mkdir -p "$OUT/vendor/ort"
for f in ort.all.min.mjs ort-wasm-simd-threaded.jsep.mjs ort-wasm-simd-threaded.jsep.wasm \
         ort-wasm-simd-threaded.asyncify.mjs ort-wasm-simd-threaded.asyncify.wasm; do
  cp "$TMP/package/dist/$f" "$OUT/vendor/ort/"
done
printf "onnxruntime-web %s, MIT License, Copyright (c) Microsoft Corporation.\nhttps://github.com/microsoft/onnxruntime/blob/main/LICENSE\n" "$ORT_VERSION" > "$OUT/vendor/ort/LICENSE.txt"
rm -rf "$TMP"

touch "$OUT/.nojekyll"
du -sh "$OUT" | cut -f1 | sed 's/^/site size: /'
