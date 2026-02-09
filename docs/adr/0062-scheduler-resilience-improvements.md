# ADR 0062: Scheduler Resilience Improvements

## Status
Implemented

## Context
The app uses an in-process, thread-based scheduler with a watchdog (ADR 0024).
This is intentionally lightweight for local/single-instance deployments, but we still want it to be resilient to:

- Long-lived threads holding stale DB connections
- Timezone/DST issues for `DailyAt(...)` schedules
- Jitter semantics drifting from what docs/UI imply (± jitter vs only delaying)
- Tasks that fail repeatedly (log storms, integration hammering)
- Tasks that hang (watchdog only restarts dead threads)
- Low observability (hard to know last run, next run, failures)

Some baseline hardening is already implemented (DB connection cleanup around task runs, timezone-correct `DailyAt`, ± jitter, basic per-task status in `get_scheduler_status()`), but we want to explicitly track the remaining improvements.

## Decision
Incrementally harden the existing scheduler (keep the in-process model) with:

1) **Thread/DB hygiene**
   - Ensure all scheduler threads call `close_old_connections()` at safe points (before/after sleeps and task executions).

2) **Time correctness**
   - `DailyAt(...)` uses Django’s configured timezone (`timezone.localtime(...)`).
   - `Every(..., jitter=N)` behaves as “±N seconds” (bounded so it never schedules in the past).

3) **Observability**
   - Track and expose per-task status: `next_run_at`, `last_started_at`, `last_finished_at`, `last_duration_seconds`, `consecutive_failures`, and a coarse `last_error`.
   - Prefer reporting this from a single place (`scheduler.get_scheduler_status()`), and keep it cheap enough for frequent polling.

4) **Failure mitigation**
   - Add optional per-task **circuit breaker/backoff** after consecutive failures (e.g. exponential backoff, capped).
   - Make backoff visible in status (next run adjusted / “suspended until” timestamp).

5) **Hung-task detection**
   - Add “task appears stuck” detection based on max runtime thresholds (cannot kill threads, but should surface loudly and optionally stop rescheduling).

6) **Configuration knobs**
   - Allow per-task enabling/disabling without code changes (env vars and/or `SystemConfig`), while keeping the default “just works” behavior.

7) **Safety for future multi-process**
   - If we ever run multiple server workers, add a best-effort leader lock (Postgres advisory lock) so only one process schedules tasks.
   - Keep it optional so local single-instance setups don’t become more complex.

## Alternatives Considered
- Keep the scheduler as-is and accept occasional manual intervention for failures/hangs.
- Replace with Celery/RQ + Redis (more resilient, but adds operational weight).
- Replace with `django-cron` / OS cron (simple, but loses in-process status and increases environment coupling).

## Consequences
- More scheduler complexity and more status state to maintain.
- Some behavior changes are user-visible (timezone-correct `DailyAt`, jitter semantics).
- Hung-task handling is inherently limited by Python threads (detect/alert/stop scheduling, but cannot kill).

## Todos
- Add circuit breaker/backoff for failing tasks.
- Add max-runtime (“stuck task”) detection and reporting.
- Add per-task enable/disable controls (env/SystemConfig).
- Add a minimal health endpoint or admin view for scheduler status consumption (if needed).
- (Optional) Implement Postgres advisory lock leader-election for multi-worker deployments.
