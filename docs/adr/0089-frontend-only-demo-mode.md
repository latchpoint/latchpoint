# ADR-0089: Frontend-Only Demo Mode

**Status:** Proposed
**Date:** 2026-05-02
**Author:** Leonardo Merza

## Context

### Background

Latchpoint is a self-hosted alarm app. To evaluate the UX today, a prospective user must clone the repo, run Docker (Postgres + backend + frontend + MQTT), seed a database, and log in — minutes of friction for a 30-second look. Even contributors who only want to see what a screen looks like before changing it must boot the full stack.

The user's ask: a public, browser-only build of the React app that boots with a realistic dataset and lets a visitor exercise every major feature (alarm states, rules, codes, door codes, control panels, integrations, settings, events). Any mutation — arming the alarm, adding a code, editing a rule — must affect only in-memory state and reset on refresh. No backend, no database, no broker. One URL.

### Current State

This branch (`feat/feature-showcase-readme-screenshots`) added a `--demo` flag to `backend/alarm/management/commands/seed_test_home.py` (~630 net lines) that writes ~70 objects to PostgreSQL inside `transaction.atomic()`:

```python
# backend/alarm/management/commands/seed_test_home.py:984
with transaction.atomic():
    AlarmSystem.objects.create(...)
    self._seed_notification_providers(profile=primary_profile)
    self._seed_alarm_event_history()
    self._seed_frigate_detections()
```

A Playwright screenshot harness (`scripts/screenshots/take-shots.mjs`) drives a real backend over HTTP, logging in via `/api/auth/login/` (line 61) and capturing PNGs that are checked into `docs/screenshots/` and embedded in the README.

This work is valuable as a **screenshot-generation aid** but is unsuitable as a public playground:

- It requires PostgreSQL + Daphne + MQTT to run.
- Visitor mutations persist to the real database.
- It maintains a parallel demo dataset alongside whatever a frontend playground would use — two sources of "what does Latchpoint look like" to keep in sync.

### Frontend data layer (intercept candidates)

- **Single HTTP client** — `ApiClient` singleton at `frontend/src/services/api.ts:61`, used by every feature. Handles CSRF (auto-fetches `/api/auth/csrf/` at line 82), snake↔camel transforms (lines 21–46), and ADR-0025 envelope unwrapping (line 209).
- **Single `QueryClient`** — built at module scope in `frontend/src/App.tsx:43`. No persistor configured today. Centralized query keys at `frontend/src/types/api.ts:58`.
- **Auth gate** — `ProtectedRoute` (`frontend/src/components/ProtectedRoute.tsx:11`) checks `useAuth().isAuthenticated`; login is `POST /api/auth/login/` returning `{ user, accessToken, refreshToken, requires2FA }` (the actual session is cookie-based on the backend, not stored client-side).
- **WebSocket** — `wsManager` singleton at `frontend/src/services/websocket.ts:190`; `AlarmRealtimeProvider` writes incoming deltas into the TanStack Query cache (`frontend/src/realtime/AlarmRealtimeProvider.tsx:48`). Drives countdowns, "armed → triggered" transitions, and live entity sync.
- **MSW** — already a dev dependency, but only configured for Node tests (`frontend/src/test/msw/server.ts:1` uses `setupServer()` from `msw/node`). No `mockServiceWorker.js` in `public/` and no `setupWorker()` call exists yet.

### Constraints

- No backend, no auth provider, no MQTT, no real WebSocket. State must not leave the browser.
- Bundle must be deployable to any static host (GitHub Pages, Vercel, Netlify, S3). Picking the host is **out of scope** for this ADR.
- The demo build **must not** enable TanStack Query persistence (e.g. `persistQueryClient`). The "refresh resets state" property is part of the contract — if a future contributor adds a persistor for prod UX, the demo loses its reset guarantee silently.
- The non-demo `seed_test_home` paths must continue to work — `CLAUDE.md`'s "quick test login" recipe relies on them, and they are unrelated to the showcase use case.

## Decision

Build the demo as a **second Vite build target**, gated by `VITE_DEMO_MODE=true`, and **retire the backend `--demo` seed** so the project has a single showcase channel.

The demo build:

1. **Intercepts HTTP at the network layer with MSW (`setupWorker`).** Add a browser worker (`frontend/public/mockServiceWorker.js`) and a separate handler tree under `frontend/src/demo/handlers/` (one file per domain, mirroring the routes in `frontend/src/services/endpoints.ts:1`). The existing `ApiClient` is untouched — it keeps doing CSRF, transforms, and envelope unwrapping against fake endpoints, so demo behavior matches prod behavior end-to-end.

2. **Stubs `wsManager`** with a scripted emitter that mutates the same in-memory stores and pushes deltas the way Channels would. Countdowns animate, "armed → triggered" transitions happen on a script, and the dashboard feels alive.

3. **Hand-crafted TS fixtures** under `frontend/src/demo/fixtures/` — one file per domain (alarm, codes, doorCodes, rules, sensors, events, integrations, panels, scheduler, notifications, users). Plain TS arrays. No codegen, no build-time backend dependency, no coupling to backend model shape.

4. **In-memory mutable stores** under `frontend/src/demo/stores/` — keyed by ID, mutated by MSW handlers. Implemented as module-level `let` bindings; a hard refresh re-executes the bundle and re-initializes from fixtures, satisfying the "no persistence" requirement automatically.

5. **A sticky "Demo mode" banner** with a **Reset** button (`window.location.reload()`) and copy explaining nothing is saved.

6. **Auto-prefilled login** — the real login screen renders, but the email and password fields are pre-filled with seeded credentials and a hint card explains the demo. Showing the login screen is part of the showcase, and prefilled credentials preserve the click-through experience.

7. **Backend `--demo` removal** — strip the `--demo` flag and its demo-specific seed paths from `backend/alarm/management/commands/seed_test_home.py`. Update `README.md`'s screenshot-tour section to point at the new demo URL instead.

## Alternatives Considered

### 1. Reuse the backend `--demo` seed dump (e.g. `manage.py dumpdata` to JSON at build)

Run the existing seed against an ephemeral SQLite at build time, dump the result to JSON, ship as a static asset. **Rejected** — couples demo fixtures to backend model shape, requires a build-time Django step in CI, and forces demo data drift to track every model migration. The user explicitly chose hand-crafted TS fixtures for this reason.

### 2. localStorage-backed persistence

Mutations would survive refresh and tab close, scoped to one browser. **Rejected** — weakens the "nothing is saved" guarantee. A visitor who returns the next day would see another visitor's edits (or worse, their own from a forgotten earlier session). The user explicitly chose in-memory only.

### 3. Swap the entire `ApiClient` at boot

Replace `frontend/src/services/api.ts:312` (`export const api = new ApiClient(...)`) with an in-memory implementation when `VITE_DEMO_MODE=true`. **Rejected** — the client does substantial work (CSRF, snake↔camel transforms, envelope unwrapping, error normalization). Replacing it forks behavior between demo and prod and risks divergence. MSW intercepts below the client, so the client's behavior stays identical between modes.

### 4. Run the real backend in-browser (e.g. `pyodide` + `sql.js`)

Bundle Django + a SQLite WASM build into the page. **Rejected** — bundle size in the tens of MB, slow boot, doesn't solve the integrations problem (still no MQTT broker / Z-Wave dongle / HA instance), and undermines the "frontend only, dead simple" goal.

### 5. Skip login entirely (auto-authenticate)

Drop visitors directly on `/` with a fake session. **Considered, rejected as default** — the login screen is part of the product surface. Prefilled credentials and a hint card give visitors the click-through experience without making them type a password.

### 6. Keep the backend `--demo` seed as a parallel showcase

Maintain both: backend seed for screenshots/dev, frontend demo for the public. **Rejected** — two datasets to maintain, drift inevitable, the public demo eventually becomes the screenshot source anyway (it's deterministic, no Docker, no auth flake). Consolidating to one is the cleaner story.

## Consequences

### Positive

- Anyone with a URL can evaluate Latchpoint in 30 seconds, on any device, without installing anything.
- Reuses existing MSW + TanStack Query plumbing — minimal new infrastructure, no new dependencies in the prod bundle.
- Zero security surface: no real backend, no real data, no real auth. Cannot leak secrets because there are none.
- Doubles as a fixture corpus the team can later reuse for offline UI development or a Storybook setup.
- Removing the backend `--demo` seed deletes ~630 lines of Django code that exists solely to populate showcase data.

### Negative / risks

- **Feature drift.** Every new page or endpoint requires a matching MSW handler and fixture, or the demo regresses. Mitigation: the demo CI build runs on every PR and surfaces missing handlers as 404s + console errors during a headless smoke run; reviewers should treat "demo broken" as a release blocker for showcase-relevant changes.
- **Some flows can only "look real."** Real OAuth, real Pushbullet sends, real Z-Wave inclusion, real notification delivery — the demo shows the form and a "demo mode: this would call the backend" toast on submit. Acceptable; it still demonstrates the UX and the validation rules.
- **WebSocket script curation.** A useful demo needs hand-tuned timelines (initial state → motion event @ 30s → optional escalation), not just stubbed connect/disconnect. More work than a no-op stub. Mitigation: ship one curated 60-second loop on first cut; expand later.
- **Loss of the backend `--demo` dataset for screenshot generation.** The current Playwright harness (`scripts/screenshots/take-shots.mjs`) depends on `seed_test_home --demo` populating Postgres. After removal, the harness either gets retargeted at the demo bundle (cleaner — deterministic, no Docker, no auth flake) or is removed if redundant with on-demand exploration of the live demo URL. Tracked as a Todo on this ADR; not in scope to decide here. Note: the already-committed PNGs under `docs/screenshots/*.png` are a separate artifact and stay regardless.
- **Reset surprises.** Visitors who don't notice the banner may make several edits, refresh, and lose them. Mitigation: banner is sticky and always visible; "Reset" is the only button on it.

## Implementation Plan

### 1. Build flag

- Add `DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true'` to `frontend/src/constants.ts`.
- Wire `vite build --mode demo` and `vite dev --mode demo` via `frontend/.env.demo` containing `VITE_DEMO_MODE=true`.

### 2. Demo scaffold under `frontend/src/demo/`

```
frontend/src/demo/
├── fixtures/              # one TS file per domain
│   ├── alarm.ts
│   ├── codes.ts
│   ├── doorCodes.ts
│   ├── rules.ts
│   ├── sensors.ts
│   ├── events.ts
│   ├── integrations.ts
│   ├── panels.ts
│   ├── scheduler.ts
│   ├── notifications.ts
│   └── users.ts
├── stores/                # mutable in-memory stores; export reset() per store
├── handlers/              # MSW REST handlers, one file per domain
├── ws/scriptedWs.ts       # fake WebSocketManager
├── banner/DemoBanner.tsx  # sticky banner with Reset button
├── README.md              # maintenance contract
└── index.ts               # initDemoMode() boot entry point
```

### 3. App boot wiring

In `frontend/src/main.tsx`, before `<RouterProvider>`:

```ts
if (DEMO_MODE) {
  await (await import('./demo')).initDemoMode()
}
```

Conditionally render `<DemoBanner />` at the app root (above `<RouterProvider>`).

### 4. MSW browser worker

- `npx msw init public/ --save` to drop `mockServiceWorker.js`.
- Reuse handler conventions from `frontend/src/test/msw/handlers.ts:3-10` (already serves CSRF for tests).
- **Must include a `GET /api/auth/csrf/` handler** that sets the `csrftoken` cookie. `ApiClient.fetchCsrfToken()` (`frontend/src/services/api.ts:82`) calls this on first mutation; without it the app hangs at the first action.
- Each handler imports its in-memory store and mutates it; reads return current store state.

### 5. WebSocket stub (`frontend/src/demo/ws/scriptedWs.ts`)

Mirror the `WebSocketManager` interface from `frontend/src/services/websocket.ts:35-191` (`subscribe`, `send`, `close`). The stub:

- Drives deltas into the same in-memory stores so REST + WS stay coherent.
- Runs a curated 60-second loop on a `setInterval` (idle → motion event → countdown → triggered → disarmed reset).
- Is swapped in at `initDemoMode()` time by replacing the export on the wsManager module (or re-exported via a thin indirection).

### 6. Login UX

- MSW handler for `POST /api/auth/login/` accepts the seeded credentials and returns a `LoginResponse` envelope shaped per `frontend/src/types/user.ts:27`.
- Demo build sets initial form values for the login page to `admin@demo.latchpoint.app` / `demo` and renders a hint card under the form. Implemented behind a `DEMO_MODE` check on the login page itself (not a page swap).

### 7. Remove the backend `--demo` seed

- Strip the `--demo` flag and its demo-specific seed paths from `backend/alarm/management/commands/seed_test_home.py`. Non-demo paths (used by `CLAUDE.md`'s "quick test login" recipe) stay.
- Update `README.md`'s screenshot-tour section to reference the new demo URL instead of `seed_test_home --demo`.
- Leave `scripts/screenshots/` intact for now; its fate is a follow-up Todo.

### 8. Build and CI

- Add `npm run build:demo` to `frontend/package.json`: `vite build --mode demo --outDir dist-demo`.
- Add a CI job that runs `npm run build:demo` on every PR and uploads the bundle as an artifact. No deploy from this ADR.

### 9. Documentation

- `frontend/src/demo/README.md` — how to add a fixture, how to add a handler, what to do when adding a new endpoint, the "this is showcase fiction" maintenance contract.
- Add a section to root `README.md` linking the (eventual) demo URL.

## Acceptance Criteria

- `VITE_DEMO_MODE=true npm run dev` boots the app with no backend running and lands on `/login` with prefilled credentials.
- Logging in with the seeded credentials reaches `/` with a populated dashboard within one second of click.
- Every navigable route renders with seeded data: Dashboard, Rules, Codes, Door Codes, Control Panels, Settings (alarm / Home Assistant / MQTT / Z-Wave JS / Frigate / Notifications), Events, Scheduler, Onboarding.
- A visitor can: arm the system, disarm the system, add a user code, edit a user code, delete a user code, edit a rule, send a test notification (stubbed toast), edit settings — and every change is reflected in the UI immediately.
- A hard refresh (`Cmd+R` / `Ctrl+R`) returns the app to its initial fixture state. The demo build does not enable any TanStack Query persistor.
- A sticky "Demo mode — nothing is saved" banner is visible on every page; its **Reset** button forces a reload.
- `npm run build:demo` produces a `dist-demo/` static bundle servable from any static host with no server-side dependencies.
- `python manage.py seed_test_home --demo` no longer exists; `python manage.py seed_test_home` (without `--demo`) still works for the dev-login recipe in `CLAUDE.md`.

## Related ADRs

- ADR 0025 — API success envelope. MSW handlers must return responses in this shape so the existing client unwrapping works unchanged.
- ADR 0070 — Entity state debug page. Similar "render seeded data without exercising the real integration" pattern.
- ADR 0079 — UI config with encrypted credentials. Settings forms can be showcased without real secrets because the schemas drive the UI.

## References

- MSW browser setup: https://mswjs.io/docs/integrations/browser
- MSW worker initialization: https://mswjs.io/docs/api/setup-worker
- This branch's existing demo work (for contrast): `backend/alarm/management/commands/seed_test_home.py`, `scripts/screenshots/take-shots.mjs`, `docs/screenshots/`.

## Todos

- Decide on hosting target (GitHub Pages vs Vercel vs Netlify vs custom subdomain). Separate decision; not blocking the ADR.
- Decide whether to expose role-switching in the demo banner (admin / resident / guest) for richer showcase, or keep it implicit at first.
- Decide the fate of the Playwright harness (`scripts/screenshots/`): retarget at the demo bundle (deterministic, no Docker, no auth flake) or remove it entirely if redundant. Note that the already-committed PNGs under `docs/screenshots/*.png` are a separate artifact and stay regardless.
- Open a tracking issue for the implementation work; link it from this ADR once filed.
