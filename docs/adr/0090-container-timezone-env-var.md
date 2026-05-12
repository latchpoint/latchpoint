# ADR-0090: Container Timezone via `TZ` Env Var

**Status:** Proposed
**Date:** 2026-05-11
**Author:** Leonardo Merza

## Context

### Background

Latchpoint runs as a small fleet of containers (`db`, `backend`, `frontend` in dev; `db`, `app` in prod). Several features depend on the container's effective timezone:

- The scheduler's `DailyAt` schedules use `timezone.localtime()` to evaluate the next run ([ADR-0024](0024-in-process-task-scheduler.md), [ADR-0062](0062-scheduler-resilience-improvements.md), `backend/scheduler/runner.py:44`).
- Rule `time_in_range` conditions use `zoneinfo.ZoneInfo` ([ADR-0065](0065-rule-builder-when-time-ranges.md), `backend/alarm/rules/conditions.py:6`).
- The `{{now}}` template variable in rule notification messages renders in `TIME_ZONE` ([ADR-0088](0088-rule-message-template-variables.md)).
- Postgres log timestamps and SQL `now()` results use the container's POSIX timezone.

A user who runs Latchpoint outside America/Chicago and wants log timestamps + scheduler firings + notification messages in their local timezone has no clean way to do it.

### Current State

Two separate mechanisms attempt to solve this today, neither of them well:

1. **Host bind-mounts** for `/etc/localtime` and `/etc/timezone` (`docker-compose.yml:11-12, 28-29, 44-45` and `docker-compose.prod.yml:11-12, 24-25`, added in commit `d06451f`). This propagates the host timezone to libc inside the container.

2. **Django `TIME_ZONE` env var** (`backend/config/settings.py:120`, defaults to `UTC`). Drives Django's ORM and template rendering only — independent of libc.

The bind-mount approach has three problems:

- **Not portable.** Mac/Windows hosts (Docker Desktop) don't expose `/etc/localtime` and `/etc/timezone` the same way; the mount silently produces UTC or fails.
- **CI runners** typically run UTC and don't carry meaningful host-tz files, so any test that exercises localized rendering can't reproduce a non-UTC environment.
- **Cloud deployments** inherit whatever the AMI baked in, with no obvious knob.

It also splits the user-facing surface: setting "everything to America/Chicago" requires both editing `TIME_ZONE` in `.env` *and* mounting host files (or fighting the host's timezone if it differs).

The production base image (`python:3.12-slim`, `Dockerfile:23`) does **not** install `tzdata`. Removing the bind-mount today would leave the container with no IANA database — `ZoneInfo("America/Chicago")` would raise `ZoneInfoNotFoundError`.

### Requirements

- Single env var sets the timezone for libc, Postgres, and Django simultaneously.
- Works identically on Linux, Mac, and Windows hosts.
- Default behavior (no override) must remain UTC for parity with current production images.
- No host filesystem dependencies.

### Constraints

- Image size budget: adding `tzdata` adds ~3 MB to the runtime image. Acceptable.
- `TZ` is libc-honored on Linux. `django-environ` reads `os.environ` directly, so reusing the `TZ` name for the Django setting does not collide with anything special.
- Postgres official image already ships with `tzdata` and honors `TZ` natively — no Dockerfile change for `db`.

## Decision

1. **Single env var, `TZ`**, set in `.env` and surfaced through `env_file:` (or an explicit `environment:` block where the service does not load `.env`) to every container. Defaults to `UTC` if unset.
2. **Install `tzdata` in the runtime base stage of `Dockerfile`** so the IANA database is present regardless of host filesystem layout.
3. **Django's `TIME_ZONE` reads from `TZ`** (`backend/config/settings.py`), so users only set one knob.
4. **Remove the host bind-mounts** for `/etc/localtime` and `/etc/timezone` from both compose files (the lines added in `d06451f`).
5. **Propagate `TZ` to backend (and dev frontend) only; leave Postgres on UTC.** Django runs with `USE_TZ = True` (`backend/config/settings.py:122`), so the ORM stores all datetimes in UTC regardless of Postgres's session timezone. The API serializes ISO-8601 with offset (e.g. `2026-05-11T20:30:00-05:00`) and the browser localizes via `toLocaleString()` (`frontend/src/features/events/utils/dateTime.ts`). No display path goes through Postgres TZ. Keeping the storage layer canonical (UTC) matches the standard "store UTC, display local" pattern; backups and replicas don't carry timezone surprises.

## Alternatives Considered

### Keep host bind-mounts, document the requirement

Pros: No changes needed.
Cons: Doesn't address portability on non-Linux hosts or cloud deployments. Doesn't unify the two timezone surfaces (libc vs. Django).

### Two env vars: `TZ` (libc) + `TIME_ZONE` (Django)

Pros: Maximum explicitness; users can drift the two if they want (e.g. Postgres logs in UTC, Django renders in local).
Cons: Two knobs to set for the common case, and the only reason to drift them is exotic. Adds documentation burden and a subtle footgun (a user setting `TZ` and not `TIME_ZONE` would get inconsistent output between Postgres logs and Django logs).

### Bake `TZ` into the image at build time

Pros: No env var to set.
Cons: Defeats the entire point — every user's timezone would have to be a different image.

## Consequences

### Positive

- One env var, one source of truth for the *application* layer (backend libc + Django).
- Image is portable across host OSes and cloud environments.
- CI can simulate any timezone by setting `TZ` in the test env.
- Storage layer (Postgres) stays canonical UTC; backups and replicas are timezone-agnostic.

### Negative / Risks

| Risk | Mitigation |
|---|---|
| Users with existing `TIME_ZONE=` in their `.env` get silently ignored after the upgrade. | Call out in release notes; the change is to a single line in `.env.example` so the diff is obvious during upgrade review. Default `UTC` matches prior default behavior, so users who never set it see no change. |
| `tzdata` package adds ~3 MB to the image. | Negligible relative to the existing image size; tzdata is the standard solution. |
| Removing the bind-mount on a host that previously relied on it (without setting `TZ`) silently regresses the container to UTC. | Default is UTC anyway; the regression is only visible if the user *previously* relied on the host bind-mount instead of `TIME_ZONE` to localize. The migration note in the release should call out "set `TZ=` in `.env` if you previously relied on the host timezone." |
| `docker compose logs db backend` interleaves UTC (Postgres) and local-time (backend) timestamps. | Accepted trade-off. Mental-math the offset, or filter to one service at a time. The cleanliness of "storage layer is timezone-agnostic" outweighs the log-correlation friction. |

### Neutral

- `TZ` is a libc-honored variable. `django-environ`'s `env.str("TZ", ...)` simply reads `os.environ["TZ"]`; no special handling, no collision.
- The setting registry remains the single source of truth for *integration* configuration. `TZ` stays an env var because it must affect libc before Django is even imported, which the registry can't influence.
- **Postgres stays on UTC by design.** With `USE_TZ=True`, all ORM datetimes are stored in UTC regardless of session timezone; `SHOW TIME ZONE` only changes how `now()` and `to_char()` *display*. The API emits ISO-8601 with offset and the browser localizes via `toLocaleString()`. If a future operator wants Postgres logs in local time for ergonomics, they can add `command: ["postgres", "-c", "timezone=${TZ:-UTC}"]` to their override compose; the default ships UTC.

## Implementation Plan

1. Add `tzdata` to the `apt-get install` list in `Dockerfile`'s runtime base stage.
2. In both compose files, remove the `/etc/localtime` and `/etc/timezone` bind-mounts from every service.
3. In compose files, ensure `TZ` reaches the application services: backend/app inherit via `env_file: .env` (already configured); add an explicit `environment: TZ: ${TZ:-UTC}` block to the dev `frontend` service. The `db` service is intentionally left alone — Postgres stays on UTC.
4. Change `backend/config/settings.py:120` from `env.str("TIME_ZONE", default="UTC")` to `env.str("TZ", default="UTC")`.
5. Replace `# TIME_ZONE=UTC` in `.env.example` with `# TZ=UTC  # IANA timezone, e.g. America/Chicago. Drives POSIX libc and Django TIME_ZONE.`
6. Update `docs/ONBOARDING.md` references from `TIME_ZONE` to `TZ`.
7. Add a brief Timezone note to `README.md`.

## Acceptance Criteria

- [ ] AC-1: `docker compose build backend` succeeds with `tzdata` installed.
- [ ] AC-2: `docker compose run --rm backend python -c "import zoneinfo; zoneinfo.ZoneInfo('America/Chicago')"` does not raise.
- [ ] AC-3: With no `TZ` line in `.env`, `settings.TIME_ZONE == "UTC"` and `docker compose exec backend date` reports UTC.
- [ ] AC-4: With `TZ=America/Chicago` in `.env`:
  - `settings.TIME_ZONE == "America/Chicago"`,
  - `docker compose exec backend date` reports CST/CDT,
  - `docker compose exec db psql -U alarm -d alarm_db -c "SHOW TIME ZONE;"` returns `Etc/UTC` — by design; the storage layer is timezone-agnostic under `USE_TZ=True`.
- [ ] AC-5: `grep -RE "/etc/localtime|/etc/timezone" docker-compose*.yml` returns nothing.
- [ ] AC-6: `./scripts/docker-test.sh` passes (in particular the `scheduler` app — DailyAt depends on `timezone.localtime`).
- [ ] AC-7: `uvx ruff check backend/` and `uvx ruff format --check backend/` clean.

## Related ADRs

- [ADR-0024](0024-in-process-task-scheduler.md) — DailyAt schedules use `timezone.localtime`.
- [ADR-0062](0062-scheduler-resilience-improvements.md) — scheduler timezone semantics.
- [ADR-0065](0065-rule-builder-when-time-ranges.md) — `time_in_range` rule condition uses `ZoneInfo`.
- [ADR-0088](0088-rule-message-template-variables.md) — `{{now}}` template variable renders in Django `TIME_ZONE`.
- [ADR-0079](0079-ui-config-with-encrypted-credentials.md) — context for why integration credentials are DB-backed but `TZ` remains an env var (libc must see it before Django boots).

## References

- `Dockerfile:23-39` — runtime base stage where `tzdata` is added.
- `docker-compose.yml:11-12, 28-29, 44-45` — bind-mounts removed.
- `docker-compose.prod.yml:11-12, 24-25` — bind-mounts removed.
- `backend/config/settings.py:120` — Django `TIME_ZONE` reads `TZ`.
- `.env.example:17` — `# TZ=UTC` documented default.
- Commit `d06451f` (2026-05-10) — the bind-mount approach this ADR reverses.

## Todos

- After implementation, flip Status to **Implemented** and update the ADR index.
- Consider exposing the effective TZ on the `/api/system/status/` endpoint (already exposes `now()`); not required by this ADR.
