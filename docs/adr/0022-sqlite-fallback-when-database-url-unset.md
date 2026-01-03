# ADR 0022: SQLite Fallback When `DATABASE_URL` Is Unset

## Status
**Implemented**

## Context
The project primarily runs with Postgres in docker-compose, but a Postgres requirement makes lightweight local
dev and simple deployments unnecessarily heavy. Django already supports SQLite well for development and tests.

We also already have a code-level fallback to SQLite when `DATABASE_URL` is not defined, but compose-level
defaults can mask that behavior.

## Decision
- When `DATABASE_URL` is **unset**, the backend uses a local SQLite file at `backend/db.sqlite3`.
- When `DATABASE_URL` is **set**, the backend uses the configured database (Postgres remains the recommended
  default for docker-compose and production-like environments).
- Compose should not force a Postgres `DATABASE_URL` default; `.env` remains the place to opt into Postgres.

## Alternatives Considered
- Require `DATABASE_URL` in all environments: simplest mental model, but raises the barrier to entry.
- Always run Postgres in dev: closer to production, but slower/heavier and less portable.
- Add a separate `USE_SQLITE=1` toggle: explicit, but duplicates configuration and creates more combinations.

## Consequences
- Developers can run the backend with minimal configuration and no external DB dependency.
- Production deployments must still set `DATABASE_URL` explicitly (SQLite is not the production default).
- SQLite-specific differences (locking/concurrency/features) may surface; keep behavior-tested paths compatible.

## Todos
- Keep `docs/planning/sqlite-fallback-database.md` up to date as workflows evolve.
- Consider making the `db` service optional in docker-compose when running with SQLite.

