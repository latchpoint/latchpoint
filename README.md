<p align="center">
  <img src="frontend/public/latchpoint_brand.png" alt="LatchPoint" width="240" />
</p>

<p align="center">
  <strong>A self-hosted home alarm panel that puts you in control.</strong><br/>
  Django + React. Integrates with Home Assistant, MQTT, Z-Wave JS, Zigbee2MQTT, and Frigate.
</p>

<p align="center">
  <img src="docs/screenshots/dashboard-dark-desktop.png" alt="Latchpoint dashboard (dark mode)" width="900" />
</p>

---

## Why Latchpoint

- **Self-hosted, no cloud lock-in.** Your alarm logic, codes, and audit log live on your hardware.
- **Encryption at rest** for every secret (broker passwords, API tokens, door PINs) — Fernet, single key, auto-generated on first boot ([ADR 0079](docs/adr/0079-db-backed-config-encryption.md)).
- **Visual rule builder** with drag-and-drop (React QueryBuilder) — no YAML, no code paths to memorize.
- **Real-time** — every state change pushes through Django Channels to the UI; arming, triggering, and sensor events update instantly.
- **Schema-driven UI** — integration settings forms render from backend `config_schema` definitions, so adding a new integration only requires a backend handler.
- **Built for hardware** — first-class Ring Keypad v2 support over Z-Wave JS with per-device action mapping.

## Feature tour

### Alarm system

- Eight alarm states: `disarmed`, `arming`, `armed_home`, `armed_away`, `armed_night`, `armed_vacation`, `pending`, `triggered`.
- Per-state delay configuration (entry, exit, trigger).
- **Multiple settings profiles** — switch between "Home", "Vacation", or any custom profile and every dependent setting (delays, sensor behavior, allowed arming states, audio/visual feedback) follows.
- Real-time WebSocket updates so the dashboard, control panels, and HA MQTT alarm entity stay in lockstep.

<details>
<summary><strong>Dashboard screenshots</strong></summary>

| Dark | Light |
|---|---|
| <img src="docs/screenshots/dashboard-dark-desktop.png" width="450" /> | <img src="docs/screenshots/dashboard-light-desktop.png" width="450" /> |

| Dark mobile |
|---|
| <img src="docs/screenshots/dashboard-dark-mobile.png" width="280" /> |

</details>

### Rules engine

- Five rule kinds: **trigger**, **disarm**, **arm**, **suppress**, **escalate**.
- Priority-based execution with optional `stop_processing` scoping by group ([ADR 0084](docs/adr/0084-rule-stop-group.md)).
- Cooldowns and circuit breakers per rule, surfaced in the runtime state UI.
- Self-registering action handlers: `alarm_trigger`, `alarm_arm`, `alarm_disarm`, `send_notification`, `ha_call_service`, `zwavejs_set_value`, `zigbee2mqtt_light` / `_switch` / `_set_value`.
- **Rules Test page** — simulate any rule against a synthetic state snapshot before turning it on.

<details>
<summary><strong>Rule builder & test screenshots</strong></summary>

<img src="docs/screenshots/rules-list-dark-desktop.png" width="900" />

<img src="docs/screenshots/rules-test-dark-desktop.png" width="900" />

</details>

### User codes (alarm PINs)

- Four code types: **permanent**, **temporary** (date-windowed), **one-time** (max-uses=1), **service**.
- Day-of-week bitmask + time-of-day window restrictions.
- Per-state allow lists — e.g. a guest code that only works for arm/disarm but not while triggered.
- Argon2-hashed (lower-cost variant tuned for short PINs, see [commit 260f96f](https://github.com/latchpoint/latchpoint/commit/260f96f)).

<details>
<summary><strong>Code management screenshots</strong></summary>

| Dark | Light |
|---|---|
| <img src="docs/screenshots/codes-dark-desktop.png" width="450" /> | <img src="docs/screenshots/codes-light-desktop.png" width="450" /> |

</details>

### Door codes (smart locks)

- Per-lock assignment with optional slot index (smart locks expose limited slots — Latchpoint manages the mapping).
- Same scheduling primitives as user codes (start/end, day-of-week, time window, max uses).
- Source tracking (`manual` vs. `synced`) and durable audit log of `code_used` / `code_failed` / `code_synced` events.

<details>
<summary><strong>Door codes screenshots</strong></summary>

| Desktop dark | Mobile dark |
|---|---|
| <img src="docs/screenshots/door-codes-dark-desktop.png" width="600" /> | <img src="docs/screenshots/door-codes-dark-mobile.png" width="280" /> |

</details>

### Notification providers

- Pluggable handler registry: **Pushbullet**, **Discord**, **Slack**, **Webhook**, **Home Assistant**.
- Full CRUD in the UI; secrets encrypted via the handler's `encrypted_fields` declaration.
- **Durable outbox** with exponential backoff and idempotency keys — notifications survive restarts.
- Per-provider test endpoint and audit log.

<details>
<summary><strong>Notification settings screenshot</strong></summary>

<img src="docs/screenshots/settings-notifications-dark-desktop.png" width="900" />

</details>

### Integrations

| Integration | Capabilities |
|---|---|
| **Home Assistant** | Entity discovery + sync, notification services, MQTT alarm entity (auto-discovery + state publishing), live status probe |
| **MQTT** | Broker connection (TLS supported), shared transport for Z2M / Frigate / HA alarm entity. Pinned client_id within MQTT 3.1 limits ([commit c98187f](https://github.com/latchpoint/latchpoint/commit/c98187f)) |
| **Z-Wave JS** | WebSocket-based device control, entity sync, Ring Keypad v2 control panel support |
| **Zigbee2MQTT** | Inventory sync, light + switch control via MQTT |
| **Frigate** | Person/vehicle detection events with zone + confidence tracking, deterministic rule evaluation against the local detection table |

<details>
<summary><strong>Integration settings screenshots</strong></summary>

<img src="docs/screenshots/settings-home-assistant-dark-desktop.png" width="900" />
<img src="docs/screenshots/settings-mqtt-dark-desktop.png" width="900" />
<img src="docs/screenshots/settings-zwavejs-dark-desktop.png" width="900" />
<img src="docs/screenshots/settings-frigate-dark-desktop.png" width="900" />

</details>

### Control panels

- Physical keypad support — currently **Ring Keypad v2** over Z-Wave JS.
- Per-device action mapping (`disarm` → `disarmed`, `arm_home` → `armed_home`, `cancel` → `cancel_arming`, etc.).
- Beep/indicator volume control via Z-Wave Indicator CC.
- Test endpoint to verify keypad output without altering alarm state.

<details>
<summary><strong>Control panels screenshot</strong></summary>

<img src="docs/screenshots/control-panels-dark-desktop.png" width="900" />

</details>

### Scheduler

- Registry-driven background tasks (cleanup, integration health probes, status digests).
- Per-task health snapshot with consecutive-failure counter, last error, last duration.
- Append-only run history for incident review.
- Failure events surface back into the alarm event log (`scheduler_task_failed`, `scheduler_task_stuck`).

<details>
<summary><strong>Scheduler screenshot</strong></summary>

<img src="docs/screenshots/scheduler-dark-desktop.png" width="900" />

</details>

### Authentication & access control

- Email + password login (Argon2id).
- TOTP/2FA opt-in.
- Role-based access (admin, resident, guest, service).
- Server-rendered onboarding wizard for first boot.

<details>
<summary><strong>Login screenshot</strong></summary>

| Dark | Light |
|---|---|
| <img src="docs/screenshots/login-dark-desktop.png" width="450" /> | <img src="docs/screenshots/login-light-desktop.png" width="450" /> |

</details>

### Audit & events

- Every state transition, code use, sensor trigger, integration outage, and rule firing lands in the alarm event log.
- Filterable by type, state, sensor, user, time range.
- Failed code attempts tracked separately for security review.

<details>
<summary><strong>Events screenshot</strong></summary>

| Desktop dark | Mobile dark |
|---|---|
| <img src="docs/screenshots/events-dark-desktop.png" width="600" /> | <img src="docs/screenshots/events-dark-mobile.png" width="280" /> |

</details>

### Settings & profiles

- Multiple alarm settings profiles, switchable from the settings UI — integrations, delays, notification providers, and arming behavior all scope to the active profile.
- Per-profile encrypted notification provider config.
- Schema-driven generic settings form (`IntegrationSettingsForm`) so new integrations only need a backend `config_schema`.

<details>
<summary><strong>Settings (alarm) screenshots</strong></summary>

| Dark | Light |
|---|---|
| <img src="docs/screenshots/settings-alarm-dark-desktop.png" width="450" /> | <img src="docs/screenshots/settings-alarm-light-desktop.png" width="450" /> |

</details>

---

## Architecture

- **DB-backed config** ([ADR 0079](docs/adr/0079-db-backed-config-encryption.md)) — connection URLs, tokens, broker passwords, and operational settings live in `AlarmSettingsEntry` JSON blobs per profile, never in environment variables.
- **Encryption at rest** — secret fields use Fernet via `backend/alarm/crypto.py`. Single env var `SETTINGS_ENCRYPTION_KEY` (auto-generated on first boot if absent).
- **Settings registry** — `backend/alarm/settings_registry.py` is the single source of truth for setting definitions, defaults, types, JSON schemas, and which fields are encrypted.
- **Action handler registry** — rule actions self-register at `backend/alarm/rules/action_handlers/`, keyed by `type`. Adding a new action is one file.
- **Import boundary** — `alarm/rules/` and `alarm/use_cases/` must NOT import from `integrations_*` or `transports_*` (enforced by test).
- **Real-time** — Django Channels 4 + Daphne serve the WebSocket; Zustand on the frontend mirrors state through TanStack Query.

## Tech stack

**Backend** — Python 3.12 · Django 6 · Django REST Framework · Django Channels · PostgreSQL 15 · paho-mqtt · zwave-js-server-python · homeassistant-api · httpx · Argon2 · Gunicorn + Uvicorn

**Frontend** — React 19 · TypeScript · Vite · TanStack Query 5 · Zustand 5 · React Router 7 · Tailwind 4 · Radix UI · React Hook Form + Zod · React QueryBuilder 8 · MSW (test mocks)

## Quick start (local dev)

```bash
cp .env.example .env
docker compose up -d              # postgres + django + vite-dev-server
```

Frontend at `http://localhost:5427`, backend at `http://localhost:8000`.

Bootstrap an admin login:

```bash
docker compose exec -T -w /app/backend backend python manage.py shell -c "
from accounts.models import User
u, _ = User.objects.get_or_create(email='admin@testhome.local', defaults={'is_staff': True, 'is_superuser': True, 'is_active': True})
u.set_password('adminpass'); u.is_staff = True; u.is_superuser = True; u.is_active = True; u.save()
"
```

| Field | Value |
|---|---|
| URL | `http://localhost:5427/login` |
| Email | `admin@testhome.local` |
| Password | `adminpass` |

### Try the demo (frontend-only)

> **Status:** planned per [ADR-0089](docs/adr/0089-frontend-only-demo-mode.md);
> not yet implemented. Once shipped, the commands below will run the entire UI
> in your browser with no backend, no database, and no Docker — every page
> populated with hand-crafted fixture data, every mutation in-memory only.

```bash
cd frontend
npm install
npm run dev:demo            # local browser tour at http://localhost:5427
# or build a static bundle for hosting:
npm run build:demo          # outputs dist-demo/, deployable anywhere static
```

Hard refresh resets all state to the initial fixtures — no changes are saved.
The demo replaces the older backend `seed_test_home --demo` showcase seed,
which will be removed when ADR-0089 is implemented. Until then, the screenshot
tour in [`scripts/screenshots/`](scripts/screenshots/README.md) still drives a
real backend.

## Production setup

Pre-built images are pushed to `ghcr.io/latchpoint/latchpoint`:

```bash
docker pull ghcr.io/latchpoint/latchpoint:latest
docker run -d -p 80:80 --env-file .env ghcr.io/latchpoint/latchpoint:latest
```

Tags include `latest` (default branch), `sha-...` (commit), and git tag
versions. See [`.env.example`](.env.example) for environment variables and
inline notes on generating `SETTINGS_ENCRYPTION_KEY`.

A reference compose file:

```yaml
services:
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: alarm_db
      POSTGRES_USER: alarm
      POSTGRES_PASSWORD: your-secure-password
    volumes:
      - db_data:/var/lib/postgresql/data

  app:
    image: ghcr.io/latchpoint/latchpoint:latest
    env_file: [.env]
    ports: ['80:80']
    depends_on: [db]

volumes:
  db_data:
```

After first boot:

```bash
docker exec <container> python backend/manage.py migrate
docker exec -it <container> python backend/manage.py createsuperuser
```

## Development

### Lint & format

```bash
uvx ruff check backend/             # backend lint
uvx ruff format --check backend/    # backend format check
cd frontend && npx eslint src/      # frontend lint (0 errors required)
cd frontend && npx tsc -b           # frontend typecheck (project-build mode)
```

> Use `tsc -b`, not `tsc --noEmit` — `frontend/tsconfig.json` is a solution
> file with `"files": []`, so bare `tsc --noEmit` walks zero source files.

### Tests

```bash
./scripts/docker-test.sh             # full backend suite
docker compose run --rm --entrypoint sh backend \
  -c "cd backend && python manage.py test alarm.tests.test_template_render -v 2"
cd frontend && npx vitest run        # frontend suite
```

### Generating screenshots

See [`scripts/screenshots/README.md`](scripts/screenshots/README.md). The harness
intercepts integration `/status/` endpoints with mock responses so the
"connected" UI renders without standing up real brokers.

## Project structure

```
backend/
  accounts/                  # users, RBAC, alarm codes, TOTP/2FA
  alarm/                     # state machine, rules engine, settings registry
    crypto.py                # Fernet helpers (set_value_with_encryption, masking)
    rules/action_handlers/   # self-registering rule actions
    settings_registry.py     # SettingDefinition (defaults, schemas, encrypted_fields)
  control_panels/            # Ring Keypad v2 device + action mapping
  locks/                     # door codes, slot assignments, code events
  notifications/             # provider registry, dispatcher, durable outbox
  scheduler/                 # registered tasks + health snapshots
  transports_mqtt/           # MQTT broker connection manager
  integrations_home_assistant/
  integrations_zwavejs/
  integrations_zigbee2mqtt/
  integrations_frigate/

frontend/src/
  pages/                     # routed page components
  features/                  # feature modules (rules, codes, integrations, ...)
  stores/                    # Zustand stores (theme, auth, ws)
  services/                  # API clients + endpoint constants
  components/ui/             # shared Radix-based primitives

docs/adr/                    # 79 architecture decision records
docs/screenshots/            # README screenshots (see scripts/screenshots/)
schema/                      # SQL + seed_entities.json
scripts/                     # docker-*.sh helpers, screenshot harness
```

## License

See [LICENSE](LICENSE) if present in the repo. Otherwise treat as all-rights-reserved
until a license file is added.
