# Latchpoint

A self-hosted home alarm system with integrations for Home Assistant, MQTT, Z-Wave JS, Zigbee2MQTT, and Frigate. Features include a visual rules builder, user alarm codes, smart lock door codes, notification routing, control panel support (Ring Keypad v2), multiple settings profiles, and comprehensive event auditing.

## Project Overview

### Integrations
- **Home Assistant** — entity discovery, service calls, MQTT alarm entity publishing, notifications
- **MQTT** — broker connectivity (TLS supported), message transport for Z-Wave JS, Zigbee2MQTT, and Frigate
- **Z-Wave JS** — WebSocket-based device control, entity sync, control panel support
- **Zigbee2MQTT** — inventory sync, light/switch control via MQTT
- **Frigate** — person/vehicle detection events with zone and confidence tracking

### Key Features
- **Alarm states**: disarmed, arming, armed_home, armed_away, armed_night, armed_vacation, pending, triggered
- **Rules engine**: priority-based automation rules (trigger, disarm, arm, suppress, escalate) with cooldowns, circuit breakers, and a drag-drop query builder UI
- **User codes**: 4-8 digit PINs (permanent/temporary/one-time/service) with per-state restrictions
- **Door codes**: smart lock access codes with time windows, day-of-week, and max-use limits
- **Notifications**: Pushbullet, Discord, Slack, Home Assistant, Webhook (more planned); durable outbox with retry
- **Control panels**: Ring Keypad v2 with per-device action mapping
- **Multiple settings profiles**: switchable alarm configurations
- **Entity tagging**: tag and filter entities across all integrations
- **Scheduler**: registered tasks with failure tracking and backoff

## Backend Stack

- **Python 3.12** / **Django 6.x** / **Django REST Framework 3.16+**
- **Django Channels 4.3+** with Daphne (WebSocket support for real-time state updates)
- **PostgreSQL 15** (psycopg2-binary)
- **paho-mqtt 2.0+** (MQTT client)
- **zwave-js-server-python 0.62+** / **websocket-client** (Z-Wave JS)
- **homeassistant-api** (HA REST client)
- **httpx** (async HTTP)
- **Argon2-cffi** (password hashing)
- **django-environ**, **django-cors-headers**
- **Gunicorn + Uvicorn** (production ASGI)

### Django Apps
| App | Purpose |
|-----|---------|
| `accounts` | Users, RBAC, alarm codes (UserCode), TOTP/2FA |
| `alarm` | Core alarm state machine, rules engine, sensors, entities, settings registry |
| `control_panels` | Physical keypad devices (Ring Keypad v2) |
| `locks` | Smart lock door codes, slot assignments, code events |
| `notifications` | Provider registry, handler dispatch, durable outbox |
| `scheduler` | Registered tasks with cron scheduling and failure tracking |
| `transports_mqtt` | MQTT broker connection management |
| `integrations_home_assistant` | HA entity discovery, MQTT alarm entity |
| `integrations_zwavejs` | Z-Wave JS WebSocket integration |
| `integrations_zigbee2mqtt` | Zigbee2MQTT inventory sync and control |
| `integrations_frigate` | Frigate detection events and zone tracking |

## Frontend Stack

- **React 19** / **TypeScript** / **Vite**
- **TanStack Query 5** (data fetching/caching)
- **Zustand 5** (state management)
- **React Router DOM 7** (routing)
- **Tailwind CSS 4** / **Radix UI** / **Lucide** icons
- **React Hook Form 7** + **Zod 4** (form validation)
- **React QueryBuilder 8** with drag-drop (rules builder UI)
- **xterm** (terminal UI)
- **MSW** (API mocking for tests)

### Frontend Structure
- `frontend/src/pages/` — page components (dashboard, rules, codes, door codes, settings tabs, setup wizards, events, scheduler, etc.)
- `frontend/src/features/` — feature modules (alarmSettings, codes, doorCodes, events, frigate, homeAssistant, mqtt, notifications, rules, rulesTest, sensors, zigbee2mqtt, zwavejs, etc.)

## Lint & Format

### Backend (Python)
```bash
uvx ruff check backend/           # lint
uvx ruff format --check backend/  # format check (dry run)
uvx ruff format backend/          # auto-format
```

### Frontend (TypeScript/React)
```bash
cd frontend
npx eslint src/          # lint (0 errors required; warnings OK)
npx tsc --noEmit         # type check
```

## Tests

### Backend
```bash
# Runs in Docker (Django not installed locally)
python manage.py test
```

### Frontend
```bash
cd frontend
npx vitest run
```

## CI/CD

- **PR checks** (`.github/workflows/ci.yml`): runs backend tests (accounts, alarm, control_panels, locks, notifications, scheduler) and frontend tests
- **Build & push** (`.github/workflows/build-and-push.yml`): builds Docker image to `ghcr.io` on main push and GitHub releases

## Docker

- **Multi-stage Dockerfile**: frontend-builder (Node 20 + Vite) -> production (Python 3.12-slim + nginx + supervisor)
- **`docker-compose.yml`**: dev setup with PostgreSQL 15, backend (port 8000), frontend Vite dev server (port 5427)
- **`docker-compose.prod.yml`**: production compose
- PostgreSQL runs in a separate infra compose file (`/media/cubxi/docker/docker-compose.infra.yml`), not in this project's compose

## Architecture

- **All config is DB-backed** (ADR 0079) — connection config, credentials, and operational settings all live in `AlarmSettingsEntry` JSON blobs per profile
- **Encryption at rest** — secret fields encrypted with Fernet (`enc:v1:` prefix) via `backend/alarm/crypto.py`; single env var `SETTINGS_ENCRYPTION_KEY` (auto-generated on first boot)
- **Settings registry** (`backend/alarm/settings_registry.py`) = centralized setting definitions with defaults, types, `config_schema`, and `encrypted_fields`
- **Schema-driven UI** — `config_schema` on `SettingDefinition` drives generic frontend forms via `IntegrationSettingsForm`
- **Notification providers** — full CRUD in UI; handlers define `config_schema` and `encrypted_fields`
- **Action handler registry** (`backend/alarm/rules/action_handlers/`) = self-registering, protocol-based rule action handlers
- **Signal handlers** in MQTT/ZWaveJS/HA `apps.py` react to operational settings profile changes at runtime
- PATCH endpoints accept settings updates for HA, MQTT, and Z-Wave JS; Frigate/Zigbee2MQTT also accept settings

### Import Boundary (enforced by test)
`alarm/rules/` and `alarm/use_cases/` must **NOT** import from `integrations_*` or `transports_*`.
