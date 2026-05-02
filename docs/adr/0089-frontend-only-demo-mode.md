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

3. **Hand-crafted TS fixtures** under `frontend/src/demo/fixtures/` — one file per domain (alarm, codes, doorCodes, rules, sensors, events, integrations, panels, scheduler, notifications, users, haEntities, zwaveDevices, zigbeeDevices, frigateCameras, frigateDetections). Plain TS arrays. No codegen, no build-time backend dependency, no coupling to backend model shape. **Concrete inventory targets** (the demo is "showcase fiction" — these are minimums for credible variety, not maximums):

   | Domain | Target | Notes |
   |---|---|---|
   | Users | 4 | admin, resident, guest, service — covers RBAC variety |
   | User codes | 6 | one of each access type (permanent / temporary / one-time / service) plus 2 with per-state restrictions |
   | Door codes | 5 | permanent, time-window, day-of-week-restricted, one-time (post-burn), max-use-limited |
   | Sensors | 10 | door×3, window×2, motion×2, glass-break, smoke, water-leak — varied state mix |
   | Rules | 12 | spread across all kinds (trigger / disarm / arm / suppress / escalate), at least one using stop-processing groups (ADR-0084), one using template variables (ADR-0088), one using HA Call Service action |
   | Notification providers | 6 | one of each handler type (Pushbullet, Discord, Slack, Webhook, Home Assistant) plus a duplicate to surface ADR-0080's multi-provider flow |
   | Control panels | 1 | Ring Keypad v2 with full action mapping populated |
   | Settings profiles | 3 | Default (active), Vacation, Sleep — exercises profile-switching |
   | Alarm events | 50+ | spanning the past week; mix of state changes, triggers, code uses, integration events |
   | Scheduler tasks | 5 | mixed success/failure history to surface backoff UI |
   | Home Assistant entities | 30+ | across `light`, `switch`, `sensor`, `climate`, `lock`, `cover`, `binary_sensor`, `media_player` domains |
   | Z-Wave devices | 8 | 2 locks, 2 motion sensors, 2 multilevel switches, 1 smoke detector, 1 controller |
   | Zigbee devices | 8 | 3 bulbs, 2 contact sensors, 1 motion, 1 button, 1 plug |
   | Frigate cameras | 4 | front_door, backyard, driveway, garage — each with named zones |
   | Frigate detections | 20+ | mix of person, car, package, dog across cameras and zones |

4. **All integrations boot in "connected" state.** Every integration health endpoint (`/api/alarm/home-assistant/status/`, `/api/alarm/mqtt/status/`, `/api/alarm/zwavejs/status/`, `/api/alarm/frigate/status/`, `/api/alarm/zigbee2mqtt/status/`) returns a healthy response with synthetic-but-plausible telemetry: last-heartbeat within the last few seconds, entity / device counts matching the fixture inventory above, message-rate and uptime metrics. Status cards on the dashboard and settings tabs show green badges out of the box; "Test Connection" buttons return success after a brief simulated delay. A visitor must never see "Disconnected" or "Unknown" for an integration unless they explicitly trigger it (a Todo: a hidden "chaos" button to demo the disconnected UI).

5. **In-memory mutable stores** under `frontend/src/demo/stores/` — keyed by ID, mutated by MSW handlers. Implemented as module-level `let` bindings; a hard refresh re-executes the bundle and re-initializes from fixtures, satisfying the "no persistence" requirement automatically.

6. **A sticky "Demo mode" banner** with a **Reset** button (`window.location.reload()`) and copy explaining nothing is saved.

7. **Auto-authenticate** — the demo's MSW `GET /api/users/me/` returns the seeded admin user unconditionally, so visitors land directly on `/` (the dashboard) on first paint. Showing the login screen as the default landing was considered (Alternative §5) but rejected in implementation: the auto-auth path keeps the click-through to a single hop, matches what `scripts/screenshots/take-shots.mjs` already assumes (the harness does not log in when `DEMO=true`), and avoids a hop visitors who came from a marketing link don't expect. The login screen remains accessible at `/login` for visitors who navigate there directly or hit logout, and prefills the seeded credentials there so the explicit click-through is still exercisable.

8. **Backend `--demo` removal** — strip the `--demo` flag and its demo-specific seed paths from `backend/alarm/management/commands/seed_test_home.py`. Update `README.md`'s screenshot-tour section to point at the new demo URL instead.

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
- **Screenshot harness retargeting.** The Playwright harness (`scripts/screenshots/take-shots.mjs`) previously depended on `seed_test_home --demo` populating Postgres; in PR #47 it was retargeted at the demo bundle via a `DEMO=true` (default) env flag. The legacy backend-driven flow is preserved behind `DEMO=false`. The already-committed PNGs under `docs/screenshots/*.png` stay; future regen will run against the demo.
- **Reset surprises.** Visitors who don't notice the banner may make several edits, refresh, and lose them. Mitigation: banner is sticky and always visible; "Reset" is the only button on it.

## Implementation Plan

### 1. Build flag

- Add `DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true'` to `frontend/src/constants.ts`.
- Wire `vite build --mode demo` and `vite dev --mode demo` via `frontend/.env.demo` containing `VITE_DEMO_MODE=true`.

### 2. Demo scaffold under `frontend/src/demo/`

```
frontend/src/demo/
├── fixtures/              # one TS file per domain
│   ├── alarm.ts            # alarm states + 3 settings profiles
│   ├── codes.ts            # 6 user codes across all access types
│   ├── doorCodes.ts        # 5 door codes with mixed restrictions
│   ├── rules.ts            # 12 rules across all kinds
│   ├── sensors.ts          # 10 sensors across types
│   ├── events.ts           # 50+ events spanning past week
│   ├── integrationHealth.ts # connected + telemetry for all 5 integrations
│   ├── haEntities.ts       # 30+ HA entities across domains
│   ├── zwaveDevices.ts     # 8 Z-Wave devices including locks
│   ├── zigbeeDevices.ts    # 8 Zigbee devices
│   ├── frigateCameras.ts   # 4 cameras with zones
│   ├── frigateDetections.ts # 20+ detections
│   ├── panels.ts           # Ring Keypad v2 with mapping
│   ├── scheduler.ts        # 5 tasks with mixed history
│   ├── notifications.ts    # 6 providers (one per type + duplicate)
│   └── users.ts            # 4 users covering RBAC variety
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
- **Integration health endpoints (`/api/alarm/{home-assistant,mqtt,zwavejs,frigate,zigbee2mqtt}/status/` and matching `/test-connection/` POSTs) must return success with seeded telemetry by default.** Each handler reads from a shared `integrationHealth` store seeded as connected at boot, so dashboard cards and settings tabs show green badges on first paint without any visitor action. Test-connection POSTs return success after a 300–800ms simulated delay so the loading UI is exercised.

### 5. WebSocket stub (`frontend/src/demo/ws/scriptedWs.ts`)

Mirror the `WebSocketManager` interface from `frontend/src/services/websocket.ts:35-191` (`subscribe`, `send`, `close`). The stub:

- Drives deltas into the same in-memory stores so REST + WS stay coherent.
- Runs a curated 60-second loop on a `setInterval` (idle → motion event → countdown → triggered → disarmed reset).
- Is swapped in at `initDemoMode()` time by replacing the export on the wsManager module (or re-exported via a thin indirection).

### 6. Login UX

- MSW handler for `POST /api/auth/login/` accepts the seeded credentials and returns a `LoginResponse` envelope shaped per `frontend/src/types/user.ts:27`.
- Demo build sets initial form values for the login page to `admin@demo.latchpoint.app` / `demo` and renders a hint card under the form. Implemented behind a `DEMO_MODE` check on the login page itself (not a page swap).
- Visitors land on `/` directly via auto-auth (per Decision §7); the login screen is opt-in, reachable by navigating to `/login` or via logout.

### 7. Remove the backend `--demo` seed (done in PR #47)

- Strip the `--demo` flag and its demo-specific seed paths from `backend/alarm/management/commands/seed_test_home.py`. Non-demo paths (used by `CLAUDE.md`'s "quick test login" recipe) stay. **Status:** done via revert of commit `6a9f1e4` in PR #47.
- Update `README.md`'s screenshot-tour section to reference the new demo URL instead of `seed_test_home --demo`. **Status:** done in PR #47.
- Retarget `scripts/screenshots/` at the demo bundle. **Status:** done in PR #47 — the harness now defaults to the demo via `DEMO=true`; legacy backend flow preserved behind `DEMO=false`.

### 8. Build and CI

- Add two scripts to `frontend/package.json`:
  - `npm run dev:demo` → `vite --mode demo` (local browser tour, no backend running).
  - `npm run build:demo` → `vite build --mode demo --outDir dist-demo` (static bundle for hosting).
- Add a CI job that runs `npm run build:demo` on every PR and uploads the bundle as an artifact. No deploy from this ADR.

### 9. Documentation

- `frontend/src/demo/README.md` — how to add a fixture, how to add a handler, what to do when adding a new endpoint, the "this is showcase fiction" maintenance contract.
- Add a section to root `README.md` linking the (eventual) demo URL.

## Acceptance Criteria

- `VITE_DEMO_MODE=true npm run dev` boots the app with no backend running and lands on `/` (auto-authenticated as the demo admin per Decision §7) with a populated dashboard within one second of first paint. `/login` remains accessible for explicit click-through and prefills the seeded credentials when visited.
- Logging in via the prefilled credentials at `/login` returns to `/` with the same populated dashboard. The 2FA screen renders if a visitor toggles it on the demo user, but submission shows a "demo mode" toast (no real TOTP backend).
- Every navigable route in `frontend/src/App.tsx:108-134` renders with seeded data:
  - **Auth + onboarding** — Login (`/login`), Onboarding (`/onboarding`)
  - **Setup wizard** — `/setup`, `/setup/mqtt`, `/setup/zwavejs`, `/setup/import-sensors`. The demo user lands already onboarded by default; a "Replay setup wizard" link in the demo banner walks visitors through the wizard against fake integration health.
  - **Core pages** — Dashboard (`/`), Rules (`/rules`), Rules Test sandbox (`/rules/test`), Codes (`/codes`), Door Codes (`/door-codes`), Events (`/events`), Control Panels (`/control-panels`), Scheduler (`/scheduler`)
  - **Debug** — Entities (`/debug/entities`), Logs (`/debug/logs`)
  - **Settings tabs** — alarm, notifications, home-assistant, mqtt, frigate, zwavejs. The `/settings/zigbee2mqtt` route redirects to `/settings/mqtt` (`App.tsx:132`) and inherits coverage automatically.
- **Every interactive control on every page is exercisable end-to-end** — not just navigable. The demo is a "playground", not a screenshot tour. Specifically, a visitor can complete the following flows, and every change is reflected in the UI immediately:

  | Page | Flows that must work in demo |
  |---|---|
  | Dashboard | Arm (away / home / night / vacation); cancel a pending arm during countdown; disarm with a seeded PIN; observe a scripted motion event triggering the alarm; acknowledge a triggered alarm |
  | Rules | Create a rule from scratch via the drag-drop QueryBuilder; edit; duplicate (per ADR-0085); delete; toggle enabled; reorder priority; assign to a stop-processing group (ADR-0084); use template variables in a notification message (ADR-0088); use the HA Call Service action with the entity picker |
  | Rules Test | Pick a seeded rule; set fake entity state via the form; run the simulation; see trigger / no-trigger result with action chain output |
  | Codes | Create a 4–8 digit user code; pick access type (permanent / temporary / one-time / service); set per-state restrictions; edit; delete; toggle PIN visibility |
  | Door Codes | Create a door code with time windows / day-of-week / max-uses; assign to a seeded lock; view the code-events audit trail; toggle visibility (per ADR-0083) |
  | Events | Filter by type / severity / time range; paginate; open a detail modal |
  | Control Panels | View the seeded Ring Keypad v2; edit its action mapping; trigger a simulated key press to see the resulting alarm state change |
  | Scheduler | View task list with next-run times; toggle a task enabled / disabled; view failure history with backoff metadata |
  | Settings — Alarm | Switch the active settings profile (Default / Vacation / Sleep); edit profile fields; create a new profile; delete a non-active profile |
  | Settings — Notifications | Full provider CRUD (create / edit / delete) for each handler type; "Send Test" returns a stubbed success toast; encrypted fields render masked then editable, demonstrating the ADR-0079 flow |
  | Settings — HA / MQTT / Z-Wave / Frigate | Edit connection fields; "Test Connection" returns success after a simulated delay; entity / device / camera lists populate from the fixture inventory |
  | Debug — Entities | Browse all seeded entities across HA / Z-Wave / Zigbee; tag and untag entities; live state badges update from the scripted WS |
  | Debug — Logs | Stream synthetic log lines; filter by severity |
  | Setup wizard | Replay the wizard via the demo banner link; advance through MQTT, Z-Wave, and sensor-import steps with fake "Test Connection" success at each |

- **All integrations show as connected with populated device inventories on first paint** — Home Assistant, MQTT, Z-Wave JS, Zigbee2MQTT, and Frigate status cards display green badges, recent heartbeats, and the device / entity / camera counts from the fixture inventory. A visitor never sees "Disconnected" or "Unknown" without taking a deliberate action (e.g. a hidden chaos button, if one is added later).
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
- Regenerate `docs/screenshots/*.png` from the demo bundle once the scripted WS timeline (per §5) is in place, so dynamic states (arming countdown, triggered, motion event) can be captured deterministically. The harness itself is now retargeted at the demo (see Implementation Plan §7).
- Open a tracking issue for the implementation work; link it from this ADR once filed.
