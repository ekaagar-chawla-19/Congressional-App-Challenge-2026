# @hemlock-sentinel/client

TypeScript client for the Hemlock Sentinel backend. Works in React Native / Expo,
browsers and Node 18+. No runtime dependencies.

```bash
npm install && npm run build        # dist/
npm run test:live -- p1.jpg … p6.jpg   # against a running backend (HEMLOCK_URL, default http://localhost:8000)
npm run gen                          # regenerate src/schema.d.ts after API changes
```

Usage, flows and every endpoint: [`../docs/api.md`](../docs/api.md).
