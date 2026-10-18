# HemlockID app

Phone app for HemlockID: scan a hemlock's bark, recognize which tree it is, and record its
hemlock woolly adelgid health over time. Expo SDK 58, Expo Router, TypeScript.

## Run it

```bash
cd mobile
npm ci
npx expo start        # scan the QR code with Expo Go on your phone
```

Development builds load five sample trees so every screen has something to show.
Release builds start empty.

```bash
npm run typecheck
npm run lint
```

## Layout

```
src/
  app/            routes (one file per screen)
    (tabs)/       Home, Trees, Map, Device, plus the custom tab bar
    onboarding    pair    scan    result    health    tree/[id]    about
  theme.ts        Forest Floor colors, status colors, spacing, fonts
  ui.tsx          shared components (Screen, Button, Card, Row, Badge, ...)
  icons.ts        the app's icon set (per-icon imports keep the bundle small)
  data.ts         SQLite schema, queries, health rules, CSV export
  device.ts       field-unit interface, mock link, app state
  identify.ts     tree matching (placeholder until the model is served)
```

Scan flow: `scan` takes 3 to 5 bark photos, `result` ranks known trees, and `health`
records the four HWA signs and saves the scan. All data stays on the phone in SQLite.

## Placeholders to replace

- **`identify.ts`**: returns a stable pseudo-random ranking. Replace it with the real model
  (DINOv2 embedding and cosine similarity against each tree's scans), on-device or behind
  an API, and set `MATCH_THRESHOLD` from validation.
- **`device.ts`**: `link` is a mock. Implement `DeviceLink` over BLE or Wi-Fi once the
  hardware is chosen. Until then, scans use the phone camera.
- **Sync**: the setting and the pending count exist, but there is no server yet.
