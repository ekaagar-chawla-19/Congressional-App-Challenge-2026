# @hemlock-sentinel/client

TypeScript client for the Hemlock Sentinel backend. Works in React Native / Expo,
browsers and Node 18+. No runtime dependencies.

```bash
npm install && npm run build        # dist/
npm run test:live -- p1.jpg … p6.jpg   # against a running backend (HEMLOCK_URL, default http://localhost:8000)
npm run gen                          # regenerate src/schema.d.ts after API changes
```

Usage, flows and every endpoint: [`../docs/api.md`](../docs/api.md).

## Run the model on the device

`src/ondevice.ts` (`OnDeviceModel`) runs the same `hemlock.onnx` and the same decision as the server
with any ONNX Runtime JS binding (`onnxruntime-web`, `onnxruntime-react-native`, `onnxruntime-node`).
See `../docs/api.md`, "Where the model runs".

```bash
npm run build:web      # browser build -> ../src/hemlock_sentinel/api/static/ondevice.js (+ vendored onnxruntime-web)
python ../scripts/ondevice_parity_fixture.py --out test/fixture.json && npm run test:parity   # matches the server?
```
