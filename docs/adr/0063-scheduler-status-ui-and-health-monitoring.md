# ADR 0063: Scheduler Status UI and Health Monitoring

## Status
Implemented

## Related
- ADR 0024: In-Process Task Scheduler with Watchdog
- ADR 0062: Scheduler Resilience Improvements
- ADR 0025: Standardized API Response Format
- ADR 0042: Integration Status Monitoring (status UX patterns + persistence)

## Context
The app has an in-process scheduler (ADR 0024) and is adding resilience/observability improvements (ADR 0062), but today there is no first-class way to:

- See which tasks exist, their schedules, and their computed `next_run_at`
- Know when each task last ran, how long it took, and whether it is failing repeatedly
- Detect (and surface) “hung” tasks where the thread is alive but the task appears stuck
- Monitor scheduler health across restarts (in-memory status is lost)

We want an admin-friendly UI that surfaces the above, plus a backend API that provides stable, queryable status for monitoring and debugging.

### Goals
- Make the scheduler observable without SSH/log spelunking.
- Provide a small set of “useful health” signals (not a full metrics system).
- Persist enough information to survive restarts and allow basic history/recent-run views.

### Non-goals (initial scope)
- A general-purpose job runner/queue (Celery/RQ).
- A full Prometheus/OpenTelemetry metrics pipeline.
- A rich “run task now” UI (possible future enhancement; read-only first is fine).

## Decision
Add persisted scheduler execution telemetry + read-only admin UI.

### Key Decisions (answered)
1) **Scope + audience**: Admin-only, read-only UI and API in v1.
2) **Multi-process behavior**: Status is recorded per `instance_id`. We do not require multi-process support for correctness in v1, but we design the schema/API so multiple instances can coexist.
3) **Run history volume**: Do **not** write a `SchedulerTaskRun` row for every successful run of high-frequency tasks. Persist:
   - always: snapshot updates in `SchedulerTaskHealth`
   - on failure: create a `SchedulerTaskRun` row
   - optionally: sampled successes (e.g. at most 1 per task per hour) and “slow run” rows (duration over threshold)
4) **Stuck detection**: “Stuck” is derived (not a stored status):
   - `is_running=true` and `now - last_started_at > max_runtime_seconds`
   - and (if heartbeat is implemented) `now - last_heartbeat_at` exceeds a heartbeat-stale threshold
   Defaults: no stuck detection unless `max_runtime_seconds` is configured for that task.
5) **Failure signaling**: Create an `AlarmEvent` when a task reaches a failure threshold (default: 3 consecutive failures) or is detected as stuck. Notification delivery remains a future enhancement (rules/notifications can be layered later).
6) **Operational controls**: No “run now” / enable/disable from UI in v1. Per-task enable/disable remains code/env-based (ADR 0062 follow-up can add `SystemConfig` controls later).
7) **DB errors during telemetry writes**: Telemetry is best-effort; failures to write telemetry must not fail the scheduled task itself.

### 1) Persisted status (DB tables)
Add two scheduler-focused models (in the existing `scheduler` Django app unless there is a strong reason to create a new app):

1) `SchedulerTaskRun` (append-only execution history)
   - `task_name` (string; matches registry name)
   - `started_at`, `finished_at` (timestamps; `finished_at` nullable while running)
   - `status` (enum: `success`, `failure`, `skipped`, `timeout`, `running`)
   - `duration_seconds` (nullable; derived on completion)
   - `error_message` (nullable; truncated for UI safety)
   - `error_traceback` (nullable; optional, may be gated by DEBUG/setting)
   - `consecutive_failures_at_start` (int; copied from current health snapshot for debugging)
   - `instance_id` (string; identifies process/container, e.g. hostname + pid)
   - `thread_name` (string; best-effort)

2) `SchedulerTaskHealth` (one row per task per instance; upserted)
   - `task_name`, `instance_id` (unique together)
   - `enabled` (bool; as executed by this instance)
   - `schedule_type` + `schedule_payload` (e.g., `DailyAt`/`Every`, plus params for UI display)
   - `next_run_at`
   - `last_started_at`, `last_finished_at`
   - `last_duration_seconds`
   - `is_running` (bool)
   - `consecutive_failures`
   - `last_error_message` (nullable)
   - `last_heartbeat_at` (updated periodically by scheduler/watchdog loop)
   - `max_runtime_seconds` (nullable; configured per task, used by the API/UI to compute “stuck”)

Rationale:
- The UI needs both “current snapshot” and “recent history”.
- A snapshot table keeps reads cheap and supports frequent polling without heavy aggregation.
- A run-history table supports debugging (“what happened recently?”) and trend checks.

### 2) Instrument the scheduler runner
Extend scheduler execution flow to emit a structured “task started / finished / failed” lifecycle and persist updates:
- On task start: upsert `SchedulerTaskHealth` + create `SchedulerTaskRun(status=running, started_at=...)`.
- On success/failure: finalize `SchedulerTaskRun` and update `SchedulerTaskHealth` fields (including `consecutive_failures` and `last_error_message`).
- On “still running” heartbeat: update `SchedulerTaskHealth.last_heartbeat_at` (infrequent, e.g. every 30–60s per running task).

This should be compatible with ADR 0062’s “hung-task detection”:
- A task is “stuck” when `is_running=true` and `now - last_started_at > max_runtime_seconds` (task-specific threshold; default unset).
- Stuck detection is a presentation concept (UI/API), not a forced kill (threads cannot be killed safely).

### 3) Backend API endpoints (admin-only)
Add DRF endpoints with standardized response envelopes (ADR 0025):
- `GET /api/scheduler/status/`
  - Returns instance-level scheduler health (`instance_id`, uptime-ish timestamps, task counts, “any stuck tasks”, etc.)
  - Returns per-task snapshot list (from `SchedulerTaskHealth`), including a derived `status` field (OK / failing / running / stuck / disabled)
- `GET /api/scheduler/tasks/<task_name>/runs/`
  - Paginated recent runs from `SchedulerTaskRun` (default: latest first)
  - Supports filters: `status`, `since`, `instance_id` (optional; keep simple)

Permissions:
- Staff/admin-only by default, similar to other operational endpoints.

### 4) Frontend UI (admin-only)
Add a “Scheduler” operational page that:
- Shows a table of tasks with: enabled, next run, last run, duration, consecutive failures, and a status badge (OK / Failing / Running / Stuck / Disabled).
- Provides a detail drawer/panel with last error + recent run history for a selected task.
- Polls the status endpoint at a modest interval (e.g. 5–10s) and uses the existing error boundary patterns.

### 5) Data retention
Add a cleanup strategy to avoid unbounded growth:
- Keep `SchedulerTaskRun` for **30 days**, plus a per-task cap (e.g. **max 500 rows per task**) to protect against misconfiguration.
- Implement cleanup as a scheduled task so it also exercises the monitoring stack.

## Alternatives Considered
- **In-memory status only**: simplest, but loses visibility after restarts and offers no history.
- **Log-only approach**: no schema changes, but poor UX and hard to query/monitor.
- **Use existing `SystemStatus`/integration status tables**: mixes concerns; scheduler health is distinct from integration health.
- **Prometheus/OpenTelemetry**: powerful, but a larger operational commitment than needed right now.
- **Replace scheduler with Celery/RQ**: improves execution guarantees but adds infrastructure (Redis) and complexity.

## Consequences
- Adds DB writes around task execution; needs to be efficient and resilient to transient DB issues.
- Requires migrations and a retention policy.
- Requires careful thinking for multi-process deployments (multiple instances will produce multiple `instance_id` snapshots).

## Todos
- Implement `SchedulerTaskRun` + `SchedulerTaskHealth` models, migrations, and indexes.
- Add scheduler instrumentation + instance identity helper.
- Add cleanup/retention task for run history.
- Add admin-only DRF endpoints + serializers + basic tests.
- Add frontend “Scheduler” page and routing entry (admin-only).
- Emit `AlarmEvent`s for repeated failures / stuck tasks (thresholds configurable; notifications later).
