# Planning: SQLite Fallback Database (No DB Config)

## Goal
Make local development and lightweight deployments work without any explicit database configuration by
defaulting to a local SQLite file when `DATABASE_URL` is not set.

Related ADR: `docs/adr/0022-sqlite-fallback-when-database-url-unset.md`

## Current Behavior
- Django config already supports a fallback:
  - `backend/config/settings.py` reads `DATABASE_URL`, and defaults to `sqlite:///backend/db.sqlite3` if unset.
- `docker-compose.yml` loads environment from `.env` and does not force a Postgres `DATABASE_URL` default, so
  the SQLite fallback can be used in Compose by omitting `DATABASE_URL` from `.env`.

## Proposed Behavior
- **If `DATABASE_URL` is not defined**, the backend uses SQLite at `backend/db.sqlite3`.
- **If `DATABASE_URL` is defined**, the backend uses that database (e.g., Postgres in docker-compose).

## Developer Workflows

### Local (no docker)
- Create `.env` (or export env vars) without `DATABASE_URL`.
- Run:
  - `python backend/manage.py migrate`
  - `python backend/manage.py runserver 0.0.0.0:5427`
- Confirm `backend/db.sqlite3` is created and migrations succeed.

### Docker Compose
- Default path (recommended): keep `DATABASE_URL` in `.env` (Postgres).
- SQLite path: remove `DATABASE_URL` from `.env` and rebuild/restart the `web` service.
  - Note: `db` will still start unless we make it optional in a follow-up.

## Implementation Steps
1. Stop injecting a default `DATABASE_URL` in `docker-compose.yml`.
2. Clarify in `.env.example` that `DATABASE_URL` is optional and that removing it uses SQLite.
3. Add an ADR documenting this decision and the expected production posture (explicit Postgres config).

## Acceptance Criteria
- With `DATABASE_URL` unset, `python backend/manage.py migrate` creates/uses `backend/db.sqlite3`.
- With `DATABASE_URL` set to Postgres, the existing docker-compose workflow continues to work.
- Docs clearly communicate which path is intended for production (explicit Postgres) vs. local/dev (SQLite is OK).

## Risks / Trade-offs
- SQLite has different locking/concurrency behavior than Postgres; it is not a production default.
- Some query patterns/features may behave differently across engines; keep tests engine-agnostic where possible.
