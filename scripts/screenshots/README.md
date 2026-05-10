# Screenshot harness

Playwright-based driver that captures the screenshots referenced from the
project [README.md](../../README.md). Output lands in
[`docs/screenshots/`](../../docs/screenshots/).

By default the harness targets the **frontend-only demo bundle** (ADR-0089) —
no backend, no Docker, no real auth, no broker mocks. A legacy backend-driven
flow is preserved behind `DEMO=false`.

## Run the tour (default — against the demo)

1. Start the demo dev server in another shell:

   ```bash
   cd frontend
   npm install
   npm run dev:demo            # serves on http://localhost:5427
   ```

2. Run the harness:

   ```bash
   cd scripts/screenshots
   npm install
   npx playwright install chromium  # one-time browser download
   node take-shots.mjs              # capture every shot in the manifest
   ```

   Capture only specific shots by name (matches `manifest.json` `shots[].name`):

   ```bash
   node take-shots.mjs dashboard rules-list door-codes
   ```

The demo's MSW handlers return a logged-in admin from `/api/users/me/`
regardless of session state, so the harness skips its API login step entirely.
All integration health endpoints (`/api/alarm/*/status/`) already return a
"connected" response from the demo's handlers, so the manifest's `globalMocks`
are also skipped — MSW handles them.

## Run against a real backend (legacy flow)

Set `DEMO=false` and point the harness at a running backend stack with the
`seed_test_home` showcase dataset. (The `--demo` flag for `seed_test_home` was
removed when the frontend demo replaced it; for legacy backend captures you
need to seed the data manually or run an older revision.)

```bash
DEMO=false \
FRONTEND=http://localhost:5427 BACKEND=http://localhost:8000 \
EMAIL=admin@testhome.local PASSWORD=adminpass \
node take-shots.mjs
```

In legacy mode the harness logs in via `POST /api/auth/login/` and overlays
`globalMocks` from `manifest.json` so integration cards render their connected
state without needing real brokers.

## How it works

- `manifest.json` is the source of truth for which shots are captured. Each
  entry specifies a route, the themes to capture (`dark` / `light`), and the
  viewports (`desktop` / `tablet` / `mobile`).
- The driver primes the Zustand `alarm-theme` value via `addInitScript`,
  navigates with `waitUntil: 'networkidle'`, then screenshots full-page at
  2x DPI.
- In demo mode the page boots, `initDemoMode()` registers the MSW worker
  before React renders, and every `/api/*` request is intercepted in-browser
  with the seeded fixtures.

## Adding a new shot

1. Add an entry to `manifest.json` `shots[]`:

   ```json
   { "name": "my-feature", "route": "/some/path", "themes": ["dark"], "viewports": ["desktop"] }
   ```

2. (Legacy backend mode only) If the page hits a new "live probe" backend
   endpoint that should appear healthy, add a matching entry to `globalMocks`.
   Demo mode handles this via MSW handlers in `frontend/src/demo/handlers.ts`.

3. Re-run: `node take-shots.mjs my-feature`.
