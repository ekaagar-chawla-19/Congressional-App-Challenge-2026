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
fills it in). Pick **Cooper Creek Scenic Area, Chattahoochee NF**: 64 sample hemlocks along Cooper
Creek and its tributaries, with Yellow Mountain, Duncan Ridge and the trails drawn on the map
(shapes approximate). Photos you scan are identified by the real model and stored on the backend.

What to try:
- **Scan** (middle tab): the in-app camera coaches you photo by photo (distance, blur, light, and
  whether the bark looks like hemlock) until you have three, then identifies the tree.
- **Hemlock check** (home): one photo, and the species model says whether it is an Eastern hemlock.
- **Map**: zoom (+/-, drag; pinch on the phone), switch layers between health, woolly adelgid,
  hemlock scale and drought stress (hotspots outlined), show sections, and **Analyze this view**
  to get the analysis of exactly the area on screen, which you can save as a section.
- **Insights**: the forest's diseases, where each is worst, quarterly trends, sections ranked by
  stress, trees that need attention, sensor averages and what to do. Tree pages show the disease
  trend by visit.

The camera inside the app needs the Expo Go app on the phone (a phone browser over plain http has
no camera access); in a desktop browser use "Use photos from the library".

**Offline demo:** "Explore the offline demo" on the sign-in screen needs no backend. It uses three
sample forests saved on the phone. It does not identify trees (the model runs on the server): after a scan you register a new tree or pick the tree yourself, with no made-up match scores.

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
    (tabs)/       Home, Trees, Map, Insights, plus the custom tab bar (Scan in the middle)
    onboarding    login    forests    device    pair    scan    result    health    tree/[id]    area    about
  api.ts          hemlock-api client (sign-in, forests, trees, identify, health check)
  session.ts      who is signed in, server or offline demo, current forest
  data.ts         trees, scans and forests: from the server, or SQLite in the offline demo
  identify.ts     tree matching: the server's model, or the offline stand-in
  MapCanvas       map: react-native-maps on the phone, a drawn terrain map on web (.web.tsx)
  Insights.tsx    forest / section / map-area analysis (diseases, hotspots, trends, sections)
  conditions.ts   the three conditions (HWA, elongate hemlock scale, drought) and their colors
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
