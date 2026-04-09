# CLAUDE.md

## Project Overview

Latchpoint is a self-hosted alarm system with a Django backend and React frontend.

- **Backend:** Django 6.x + DRF, in `backend/`
- **Frontend:** React + TypeScript + Vite + Vitest, in `frontend/`
- **ADR docs:** `docs/adr/`

## CI / Lint / Test Commands

CI runs via GitHub Actions using reusable workflows from `ljmerza/misc-actions`.

### Backend lint (must pass before merge)

```bash
uvx ruff check .           # linter
uvx ruff format --check .  # formatter
```

To auto-fix formatting: `uvx ruff format .`

### Frontend lint

```bash
cd frontend && npm run lint   # runs: eslint .
```

### Backend tests

```bash
uv run pytest --cov=accounts,alarm,control_panels,locks,notifications,scheduler --cov-report=term-missing
```

Env vars needed in CI (set automatically):
```
SECRET_KEY=ci
DEBUG=True
API_RESPONSE_ENVELOPE_ENABLED=True
LOG_LEVEL=INFO
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Frontend tests

```bash
cd frontend && npm test   # runs vitest
```

### TypeScript check (not in CI but useful)

```bash
cd frontend && npx tsc --noEmit
```

## Architecture (post ADR-0078)

- **All** integration config comes from environment variables via `backend/alarm/env_config.py`
- PATCH endpoints for all five integrations return 405
- Frontend settings pages are read-only displays
- Frigate cameras/zones are auto-discovered from MQTT events at runtime (in-memory only)
- Notification providers are auto-provisioned from env on startup via `backend/notifications/provider_registry.py`
