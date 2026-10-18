# HemlockID app

Phone app for HemlockID: sign in, pick a forest, scan a hemlock's bark, recognize which tree it is,
and record its health over time. Expo SDK 58, Expo Router, TypeScript.

## Run it

The app talks to `hemlock-api`, the Python backend in this repo, which runs the model and stores
the trees. Start both on the same computer:

```bash
# terminal 1, repo root
python -m pip install -e ".[onnx,app]"
hemlock-api

# terminal 2
cd mobile
npm ci
npx expo start
```

- **Phone:** install Expo Go, connect to the same Wi-Fi as the computer, and scan the QR code.
  The app finds the backend on the computer automatically (same address, port 8000).
- **Browser:** press `w` (or open http://localhost:8081). In Chrome, open DevTools and switch on
  the device toolbar to see it at phone size. The map is a simple plot in the browser; the phone
  shows a real map.

Sign in with the demo account `demo@hemlock.test` / `hemlock-demo` (the "Trying it out?" card
fills it in). It has two North Georgia forests of sample trees. Photos you scan are identified by
the real model and stored on the backend.

**Offline demo:** "Explore the offline demo" on the sign-in screen needs no backend. It uses three
sample forests saved on the phone, and a stand-in for the model (a stable pseudo-random ranking).

If the backend runs elsewhere, tap "Change" next to the server address on the sign-in screen, or
start Expo with `EXPO_PUBLIC_API_URL=http://<host>:8000`.

```bash
npm run typecheck
npm run lint
```

## Layout

```
src/
  app/            routes (one file per screen)
    (tabs)/       Home, Trees, Map, Device, plus the custom tab bar
    onboarding    login    forests    pair    scan    result    health    tree/[id]    about
  api.ts          hemlock-api client (sign-in, forests, trees, identify, health check)
  session.ts      who is signed in, server or offline demo, current forest
  data.ts         trees, scans and forests: from the server, or SQLite in the offline demo
  identify.ts     tree matching: the server's model, or the offline stand-in
  MapCanvas       map: react-native-maps on the phone, a plain plot on web (.web.tsx)
  kv              small settings store (SQLite key-value on the phone, localStorage on web)
  theme.ts        Forest Floor colors, status colors, spacing, fonts
  ui.tsx          shared components (Screen, Button, Card, Row, Badge, ...)
  icons.ts        the app's icon set (per-icon imports keep the bundle small)
  device.ts       field-unit interface, mock link, scan in progress
```

Scan flow: `scan` takes 3 to 5 bark photos (camera or photo library), `result` shows the server's
decision: a match with its confidence, a best guess when it is not sure, a new tree, or "not a
hemlock". `health` records the four HWA signs and saves them to that visit. Tree pages show the
backend's assessment of likely causes (HWA, elongate hemlock scale, drought) and the latest
ESP32 sensor reading (N/A when there is none).

## Still placeholders

- **`device.ts`**: `link` is a mock unit. The ESP32 sensor node in `firmware/esp32_sensors` speaks
  BLE; connecting to it from the app needs a BLE library and a development build (not Expo Go).
- **Offline demo matching** is a stand-in; real identification needs the backend.
