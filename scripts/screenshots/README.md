# Screenshot harness

Playwright-based driver that captures the screenshots referenced from the project
[README.md](../../README.md). Output lands in [`docs/screenshots/`](../../docs/screenshots/).

## Prerequisites

1. The dev stack must be running:

   ```bash
   docker compose up -d
   ```

2. The DB must be seeded with the showcase dataset (notification providers,
   door codes, control panel, varied rules, alarm-event history, Frigate
   detections):

   ```bash
   docker compose exec -T -w /app/backend backend \
     python manage.py seed_test_home --demo
   ```

   The `--demo` flag implies `--no-ha-sync`, fabricates demo entities, and
   creates the admin login `admin@testhome.local` / `adminpass`.

## Run the tour

```bash
cd scripts/screenshots
npm install
npx playwright install chromium  # one-time browser download
node take-shots.mjs
```

Capture only specific shots by name (matches `manifest.json` `shots[].name`):

```bash
node take-shots.mjs dashboard rules-list door-codes
```

Override the dev URLs or login when needed. By default `BACKEND` falls back to
`FRONTEND` so requests flow through Vite's `/api` proxy — the dev compose
stack does not expose the Django port on the host.

```bash
FRONTEND=http://localhost:5427 \
EMAIL=admin@testhome.local PASSWORD=adminpass \
node take-shots.mjs
# or, if the backend is exposed directly:
FRONTEND=http://localhost:5427 BACKEND=http://localhost:8000 \
node take-shots.mjs
```

## How it works

- `manifest.json` is the source of truth for which shots are captured. Each
  entry specifies a route, the themes to capture (`dark` / `light`), and the
  viewports (`desktop` / `tablet` / `mobile`).
- `globalMocks` in the manifest intercepts `/api/alarm/*/status/` endpoints —
  HA, MQTT, Z-Wave JS, Frigate, Zigbee2MQTT, and the HA MQTT alarm entity. The
  real implementations probe live brokers/HTTP/WebSocket; the mocks return a
  "connected" response so the integration cards render their healthy state.
- The driver logs in once per shot via the API (`POST /api/auth/login/`),
  primes the Zustand `alarm-theme` value via `addInitScript`, then navigates
  with `waitUntil: 'networkidle'` before screenshotting full-page at 2x DPI.

## Adding a new shot

1. Add an entry to `manifest.json` `shots[]`:

   ```json
   { "name": "my-feature", "route": "/some/path", "themes": ["dark"], "viewports": ["desktop"] }
   ```

2. If the page hits a new "live probe" backend endpoint that should appear
   healthy, add a matching entry to `globalMocks`.

3. Re-run: `node take-shots.mjs my-feature`.

## Why mocks instead of real services

Production integration status views (HA, MQTT, Z-Wave JS, Frigate, Z2M) are
*intentionally* reality-checking — they call into real client libraries at
request time and report the actual broker/socket state. For a screenshot tour
we want to show the connected state without standing up a Mosquitto + zwave-js
server + Frigate fleet locally. The mock layer lives entirely in the screenshot
harness so production code paths stay honest.
