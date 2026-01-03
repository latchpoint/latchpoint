# Agent Onboarding

This repo is a Django + React alarm panel that integrates with Home Assistant.
Use this file to get oriented quickly and to follow the established “how we build features” patterns.

## TL;DR (first run)
- Development: split `db` (Postgres) + `backend` (Django/Daphne) + `frontend` (Vite) services; `frontend` is exposed on `http://localhost:5427` and proxies `/api` and `/ws` to `backend`
  - `backend` is not published to a host port by default (use the frontend proxy, or `docker compose run --rm backend ...`)
- Production: single combined `app` service (Nginx serves built static files, proxies `/api` + `/ws` to Daphne)

### Configure env (required)
```bash
cp .env.example .env
```

### Start/stop (required: use helper scripts)
```bash
./scripts/docker-up.sh
./scripts/docker-down.sh
```

### Tests (external integrations disabled by default)
```bash
# Backend (Django)
./scripts/docker-test.sh
./scripts/docker-test-ha.sh

# Frontend (Vitest) - run on host...
cd frontend && npm test
# ...or in Docker (uses the `frontend` service)
./scripts/docker-shell.sh frontend sh -lc "npm ci && npm test"
```

### Shell into the backend container (for manage.py commands)
```bash
./scripts/docker-shell.sh
```

## Repo map
- Backend: `backend/`
  - Project config: `backend/config/`
  - Accounts/auth: `backend/accounts/` (custom user model, codes, onboarding/auth endpoints)
  - Alarm core domain + API: `backend/alarm/` (state machine, sensors/entity registry, rules engine, websocket, settings profiles, system status)
  - Control panels: `backend/control_panels/` (physical control panel devices like Ring Keypad v2)
  - MQTT transport: `backend/transports_mqtt/` (MQTT connection config + status)
  - Home Assistant integration: `backend/integrations_home_assistant/` (HA connection settings, entity discovery, HA MQTT alarm entity)
  - Z-Wave JS integration: `backend/integrations_zwavejs/` (Z-Wave JS connection config, entity sync, set-value)
  - Frigate integration: `backend/integrations_frigate/` (Frigate video surveillance, MQTT detection events, rules conditions)
  - Zigbee2MQTT integration: `backend/integrations_zigbee2mqtt/` (Zigbee2MQTT device sync, event triggers)
  - Notifications: `backend/notifications/` (providers, outbox/retries, delivery logs; rules `send_notification` action)
  - Locks + door codes: `backend/locks/` (door codes CRUD + HA lock discovery)
- Frontend: `frontend/` (React + TS + Vite; API client uses cookies + CSRF)
- Docs: `docs/` (active) and `docs/archived/` (completed/old)
- ADRs: `docs/adr/` (architecture decisions; see `docs/adr/0000-adr-index.md` for status tracking)
- Docker helpers: `scripts/`
- Docker runtime config: `docker/` (entrypoints, supervisord configs, Nginx config)

## Features (what exists today)
### Backend features
- **Auth + sessions (SPA-first)**: session cookies + CSRF (`GET /api/auth/csrf/`, `POST /api/auth/login/`, `POST /api/auth/logout/`).
- **Users**: list users + current user (`GET /api/users/`, `GET /api/users/me/`).
- **Token compatibility**: refresh access tokens (`POST /api/auth/token/refresh/`) + WS `?token=` fallback.
- **Onboarding + setup gating**: bootstrap (`POST /api/onboarding/`) + setup requirements (`GET /api/onboarding/setup-status/`).
- **Alarm state machine**: snapshot (`AlarmStateSnapshot`) + event log (`AlarmEvent`) with transitions via `alarm.use_cases` / `alarm.state_machine`.
- **Alarm API**:
  - state + transitions: `GET /api/alarm/state/`, `POST /api/alarm/arm/`, `POST /api/alarm/disarm/`, `POST /api/alarm/cancel-arming/`
  - events feed: `GET /api/events/`
- **WebSocket updates**: `/ws/alarm/` via Channels consumer (`backend/alarm/consumers.py`).
- **Sensors + entity registry**:
  - sensors CRUD: `GET/POST /api/alarm/sensors/`, `GET/PATCH/DELETE /api/alarm/sensors/:id/`
  - entity registry (import/sync): `GET /api/alarm/entities/`, `POST /api/alarm/entities/sync/`
- **Rules engine**: rules CRUD + evaluation tools (`/api/alarm/rules/`, `/api/alarm/rules/run/`, `/api/alarm/rules/simulate/`).
- **Alarm settings profiles**:
  - active settings snapshot: `GET /api/alarm/settings/`
  - profiles CRUD + activation: `GET/POST /api/alarm/settings/profiles/`, `GET/PATCH/DELETE /api/alarm/settings/profiles/:id/`, `POST /api/alarm/settings/profiles/:id/activate/`
  - resolved timing view: `GET /api/alarm/settings/timing/:state/`
- **System configuration (admin-only)**: list/update system config keys (`GET /api/system-config/`, `PATCH /api/system-config/:key/`).
- **Home Assistant integration**:
  - status: `GET /api/alarm/home-assistant/status/`
  - connection settings (stored in active profile; token encrypted): `GET/PATCH /api/alarm/home-assistant/settings/`
  - entity + notify service discovery: `GET /api/alarm/home-assistant/entities/`, `GET /api/alarm/home-assistant/notify-services/`
- **MQTT transport** (connection stored in active profile; password encrypted):
  - status: `GET /api/alarm/mqtt/status/`
  - connection settings: `GET/PATCH /api/alarm/mqtt/settings/`
  - test connection: `POST /api/alarm/mqtt/test/`
- **Home Assistant MQTT alarm entity** (requires MQTT enabled/configured):
  - status + settings: `GET /api/alarm/integrations/home-assistant/mqtt-alarm-entity/status/`, `GET/PATCH /api/alarm/integrations/home-assistant/mqtt-alarm-entity/`
  - publish discovery: `POST /api/alarm/integrations/home-assistant/mqtt-alarm-entity/publish-discovery/`
- **Z-Wave JS integration** (connection stored in active profile; token encrypted):
  - status: `GET /api/alarm/zwavejs/status/`
  - connection settings: `GET/PATCH /api/alarm/zwavejs/settings/`
  - test connection: `POST /api/alarm/zwavejs/test/`
  - entity sync + set-value: `POST /api/alarm/zwavejs/entities/sync/`, `POST /api/alarm/zwavejs/set-value/`
- **Codes**:
  - alarm PIN codes: `/api/codes/` (accounts `UserCode`)
  - door codes + lock assignment: `/api/door-codes/` and `/api/locks/available/` (locks app)
- **Control panels** (physical control panel devices):
  - device CRUD: `GET/POST /api/control-panels/`, `GET/PATCH/DELETE /api/control-panels/:id/`
  - device test (beep): `POST /api/control-panels/:id/test/`
  - supports Ring Keypad v2 via Z-Wave JS with volume control, action mapping
- **Frigate integration** (video surveillance via MQTT):
  - status: `GET /api/alarm/integrations/frigate/status/`
  - settings: `GET/PATCH /api/alarm/integrations/frigate/settings/`
  - options (cameras/zones for rules): `GET /api/alarm/integrations/frigate/options/`
  - detections feed: `GET /api/alarm/integrations/frigate/detections/`
  - rules engine conditions: trigger rules on person/vehicle detections by camera/zone
- **Zigbee2MQTT integration** (Zigbee device control via MQTT):
  - status: `GET /api/alarm/integrations/zigbee2mqtt/status/`
  - settings: `GET/PATCH /api/alarm/integrations/zigbee2mqtt/settings/`
  - devices: `GET /api/alarm/integrations/zigbee2mqtt/devices/`
  - device sync: `POST /api/alarm/integrations/zigbee2mqtt/devices/sync/`
  - rules-driven Zigbee control via THEN action `zigbee2mqtt_set_value`; action/state ingest for rules triggers
- **System status monitoring** (real-time integration health):
  - WebSocket broadcast of status changes to `/ws/alarm/` clients
  - cached status for all integrations (MQTT, HA, Z-Wave JS, Frigate, Zigbee2MQTT)
- **Notifications** (rules-driven, async delivery; see ADR 0044):
  - providers + logs: `GET/POST /api/notifications/providers/`, `GET /api/notifications/logs/`
  - provider metadata: `GET /api/notifications/provider-types/`
  - delivery semantics: rules `send_notification` action enqueues an outbox record and returns “accepted for delivery”
  - worker: scheduled task `notifications_send_pending` processes outbox records with retry/backoff
  - Home Assistant “system provider”: `POST /api/notifications/providers/ha-system-provider/test/` (virtual provider when HA configured)

### Frontend features
- **Cookie + CSRF API client**: `frontend/src/services/api.ts` (`credentials: 'include'`, auto-CSRF priming).
- **Pages**: `frontend/src/pages/`
  - Auth: `LoginPage.tsx`, bootstrap: `OnboardingPage.tsx`
  - Setup: `SetupWizardPage.tsx`, MQTT: `SetupMqttPage.tsx`, Z-Wave JS: `SetupZwavejsPage.tsx`, entity import: `ImportSensorsPage.tsx`
  - Settings: routed tabs under `frontend/src/pages/settings/` (Alarm, MQTT, Home Assistant, Z-Wave JS, Notifications)
  - Operations: `DashboardPage.tsx`, `EventsPage.tsx`, `RulesPage.tsx`, `RulesTestPage.tsx`, `CodesPage.tsx`, `DoorCodesPage.tsx`
- **Error resilience**: feature-level error boundaries + centralized error handling (see `frontend/src/components/providers/FeatureErrorBoundary.tsx` and `frontend/src/lib/errors.ts`).
- **Client state**: React Query for server state + focused Zustand stores (see `frontend/src/stores/`).

## Fast orientation (where to look first)
- Alarm state machine core: `backend/alarm/state_machine/` and `backend/alarm/use_cases/`
- HTTP endpoints wiring: `backend/config/urls.py`, `backend/alarm/urls.py`, `backend/accounts/urls.py`, `backend/locks/urls.py`
- DRF views (thin controllers): `backend/alarm/views/`, `backend/accounts/views/`, `backend/locks/views/`
- Settings keys + defaults: `backend/alarm/settings_registry.py`
- Integrations:
  - Home Assistant: `backend/integrations_home_assistant/`, `backend/alarm/gateways/home_assistant.py`
  - MQTT: `backend/transports_mqtt/`, `backend/alarm/gateways/mqtt.py`
  - Z-Wave JS: `backend/integrations_zwavejs/`, `backend/alarm/gateways/zwavejs.py`
- Secret encryption helpers: `backend/alarm/crypto.py`
- Task scheduler: `backend/scheduler/` (in-process scheduled tasks with watchdog)
- Frontend routing/pages: `frontend/src/pages/` and `frontend/src/routes.tsx`
- Frontend API + WS clients: `frontend/src/services/api.ts`, `frontend/src/services/websocket.ts`

## Common commands
### Run a realistic demo dataset (backend container)
```bash
./scripts/docker-seed-test-home.sh
```

### Frontend tests (Vitest)
```bash
cd frontend
npm run test            # full suite
npm run test:features   # feature folders only
npm run test:watch      # watch mode
```

### Frontend tests (via Docker)
```bash
./scripts/docker-shell.sh frontend sh -lc "npm ci && npm run test:features"
```

### Targeted tests
```bash
./scripts/docker-shell.sh
python manage.py test accounts.tests.test_setup_status
python manage.py test alarm.tests.test_websocket
python manage.py test alarm.tests.test_mqtt_api
```

### Scheduled tasks
```bash
./scripts/docker-shell.sh
python manage.py list_tasks       # List registered tasks
python manage.py task_schedule    # Show next scheduled runs
python manage.py run_task NAME    # Run a task manually
```

## Architecture (what exists today)
### Backend
- **Auth**: Django session cookies for SPA + CSRF protection.
  - CSRF priming endpoint: `GET /api/auth/csrf/` (sets `csrftoken`)
  - Login creates a session: `POST /api/auth/login/`
  - Token auth still exists for compatibility (`Authorization: Bearer ...`) and for WS `?token=` fallback.
- **HTTP API**: Django REST Framework (`backend/config/settings.py` sets auth + exception handler).
- **WebSocket**: Django Channels (ASGI in `backend/config/asgi.py`, consumer in `backend/alarm/consumers.py`).
  - Cookie/session auth works via `AuthMiddlewareStack`.
  - `?token=` auth works via `backend/alarm/middleware.py` (fallback/back-compat).
- **Alarm state machine**: modules under `backend/alarm/state_machine/`.
  - `backend/alarm/services.py` is a compatibility facade; new code should prefer `alarm.use_cases` and/or `alarm.state_machine`.
- **Rules engine**: public entrypoints in `backend/alarm/rules_engine.py`, internals in `backend/alarm/rules/`.
  - Repository boundary for testability: `backend/alarm/rules/repositories.py`.
- **Settings profiles**: persisted config lives in `AlarmSettingsProfile` + `AlarmSettingsEntry` and is read via `alarm.state_machine.settings`.
- **Integrations (decomposed)**:
  - Core code depends on gateways (`backend/alarm/gateways/*`) not integration implementations.
  - Persisted integration settings are applied on startup via `python manage.py apply_integration_settings` (see `docker-compose.yml`).
- **Task scheduler**: in-process scheduler with watchdog (`backend/scheduler/`).
  - Register tasks with `@register("name", schedule=DailyAt(hour=3))` decorator.
  - Schedule types: `DailyAt(hour, minute)`, `Every(seconds, jitter)`.
  - Runs in web process (no extra containers); auto-restarts crashed task threads.
  - See `docs/adr/0024-in-process-task-scheduler.md`.

### Frontend
- API client: `frontend/src/services/api.ts`
  - Always uses `credentials: 'include'` (session cookies).
  - Automatically fetches `/api/auth/csrf/` and sends `X-CSRFToken` for unsafe requests.
- WebSocket: `frontend/src/services/websocket.ts`
  - Connects to `/ws/alarm/` and relies on cookie/session auth (preferred).
- Settings UX: routed tabs with per-tab save (see `frontend/src/pages/settings/`).

## ADR-guided "house rules" (best practices)

When adding new features, align with these decisions first; if you need to deviate, write a new ADR.

> **Full ADR index with implementation status**: [`docs/adr/0000-adr-index.md`](docs/adr/0000-adr-index.md)

### Standardized API responses (ADR 0025)
- Successful JSON responses are standardized as `{ "data": <payload> }` (optional `{ "meta": {...} }` for pagination/metadata).
- Error JSON responses are standardized as `{ "error": { "status": <code>, "message": <string>, "details"?: { <field>: string[] } } }`.
- Prefer raising DRF exceptions (e.g. `ValidationError`, `NotFound`) or domain exceptions and let `backend/config/exception_handler.py` format the response; avoid returning manual `Response(..., status>=400)` payloads unless they already match the envelope.
- Tests: DRF `response.data` reflects the *pre-render* payload; use `response.json()` when asserting on the final enveloped response body.

### ADR hygiene (required)
- When an ADR is fully implemented, update its `## Status` to **Implemented** and update `docs/adr/0000-adr-index.md` (status + counts).

### Development-stage defaults
- This app is in active development: breaking changes are acceptable.
- Prefer removing compatibility/legacy code instead of carrying long-term back-compat, unless there is a clear external dependency that must be supported temporarily.
- Keep ADRs short and action-oriented:
  - Use the `docs/adr/README.md` sections, but don’t over-plan (a small “Execution Plan” or a few “Todos” is usually enough).
  - When the ADR is about cleanup/removal, include a concrete “Removal Targets” list and a minimal checklist for safe deletion.

## How to add a backend feature (pattern)
Use this checklist to keep changes consistent and easy to test.

1) **Start with the domain boundary**
   - Alarm transitions/timers/events: `backend/alarm/state_machine/*`
   - App orchestration (what the API “does”): `backend/alarm/use_cases/*` or `backend/accounts/use_cases/*`
   - External IO (integrations): depend on `backend/alarm/gateways/*` (don’t import `backend/integrations_*` directly from core use cases)

2) **Keep views thin**
   - Put endpoint code in `backend/*/views/*.py` and delegate quickly.
   - Prefer raising domain/use-case exceptions and letting `backend/config/exception_handler.py` translate to HTTP.
   - For object-level permissions in APIViews, use `backend/config/view_utils.py`.

3) **Serializers and query performance**
   - Keep serializers in `backend/alarm/serializers/` and `backend/accounts/serializers.py`.
   - Watch for N+1 queries; add `select_related/prefetch_related` in views/use cases and lock in with tests (see existing `*prefetch*` tests).

4) **Tests**
   - Default: `./scripts/docker-test.sh`
   - Prefer unit tests for pure logic (rules engine injection/repositories are already set up for this).
   - If you need HA integration coverage, explicitly opt-in with `ALLOW_HOME_ASSISTANT_IN_TESTS=true` and keep it isolated.

## How to add a frontend feature (pattern)
- Prefer adding API calls via `frontend/src/services/api.ts` (keeps cookie + CSRF correct).
- For new backend endpoints that mutate state:
  - ensure CSRF is required and working (unsafe methods must include `X-CSRFToken`).
  - return consistent error shapes (`{"detail": "..."}`
    or DRF validation errors) so `ApiClient.handleResponse()` can show good messages.
- Keep auth assumptions aligned with the backend:
  - session cookies are the default; don’t store tokens in `localStorage`.

## Environment & configuration
- Example env: `.env.example` (copy to `.env`)
- Secrets at rest:
  - `SETTINGS_ENCRYPTION_KEY` is required to store/decrypt encrypted settings (Home Assistant token, MQTT password, Z-Wave JS token).
- API response envelope (ADR 0025):
  - `API_RESPONSE_ENVELOPE_ENABLED=true` (default) wraps success responses as `{ "data": ... }`
- Home Assistant settings:
  - Runtime HA connection is stored in the active settings profile via `/api/alarm/home-assistant/settings/`.
- MQTT settings:
  - Runtime MQTT connection is stored in the active settings profile via `/api/alarm/mqtt/settings/`.
- Dev CSRF/CORS:
  - `DEBUG=True` and `ALLOWED_HOSTS` control dev-time trusted origins; see `backend/config/settings.py`.
  - In `DEBUG=True`, `CSRF_TRUSTED_ORIGINS` is auto-populated for common dev ports (including `5427` and `3000`) if unset.
- Test gating:
  - `ALLOW_HOME_ASSISTANT_IN_TESTS=true` enables HA integration tests.
  - `ALLOW_ZWAVEJS_IN_TESTS=true` enables Z-Wave JS integration tests.

## Docs workflow
- Planning/working docs live in `docs/`.
- Completed docs move to `docs/archived/`.
- New architectural decisions go in `docs/adr/NNNN-short-title.md` using `docs/adr/README.md` template.
- **Update `docs/adr/0000-adr-index.md`** when adding/changing ADR status.

## Docker helper scripts (reference)
```bash
./scripts/docker-up.sh
./scripts/docker-down.sh
./scripts/docker-rebuild.sh
./scripts/docker-makemigrations.sh
./scripts/docker-migrate.sh
./scripts/docker-test.sh
./scripts/docker-test-ha.sh
./scripts/docker-seed-test-home.sh
./scripts/docker-shell.sh
./scripts/docker-reset.sh
```
