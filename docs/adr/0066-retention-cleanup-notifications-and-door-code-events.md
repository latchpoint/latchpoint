# ADR 0066: Retention Cleanup Tasks for Notifications and Door Code Events

## Status
Implemented

## Context
Several models in this app are intentionally append-only and can grow without bounds unless retention is enforced:

- `notifications.NotificationDelivery` (durable outbox): rows transition to `sent` or `dead` but are not pruned.
- `notifications.NotificationLog` (audit log): rows accumulate indefinitely.
- `locks.DoorCodeEvent` (audit log): rows accumulate indefinitely.

Other high-churn tables already have bounded growth via scheduler tasks (events, rule logs, sessions, scheduler runs, Frigate detections). For operational safety, the remaining append-only tables should follow the same “retention + scheduled cleanup + UI visibility” pattern.

## Decision

### 1) Add retention settings (SystemConfig)
Introduce UI-editable system config keys (using 2-level dot notation consistent with existing keys like `events.retention_days` and `rule_logs.retention_days`):

- `notification_logs.retention_days` (default: 30)
- `notification_deliveries.retention_days` (default: 30; applies to `sent`/`dead` only)
- `door_code_events.retention_days` (default: 90)

Semantics:
- `<= 0` disables cleanup (no rows are deleted). Tasks must early-return when retention is disabled to avoid accidentally deleting all rows (a zero-day cutoff equals "now").
- Cleanup tasks must never delete "in-flight" rows required for correctness (e.g., `NotificationDelivery` with `pending`/`sending`).

### 2) Add scheduler cleanup tasks
Add scheduled tasks (registered via `@register`) that:

- Delete `NotificationLog` rows where `created_at < cutoff` based on `notification_logs.retention_days`.
- Delete `NotificationDelivery` rows where `status IN (sent, dead) AND created_at < cutoff` based on `notification_deliveries.retention_days`. We use `created_at` rather than `sent_at` because `sent_at` is NULL for dead-lettered deliveries.
- Delete `DoorCodeEvent` rows where `created_at < cutoff` based on `door_code_events.retention_days`.

Tasks should:
- Run daily during the existing cleanup window, staggered to avoid overlap with existing tasks (`scheduler_cleanup_task_runs` runs at 3:15, `cleanup_rule_action_logs` at 3:30):
  - `cleanup_notification_logs`: DailyAt(hour=3, minute=5)
  - `cleanup_notification_deliveries`: DailyAt(hour=3, minute=7)
  - `cleanup_door_code_events`: DailyAt(hour=3, minute=10)
- Return the deleted row count for observability.
- Log a single structured INFO line when deletions occur.

Task file locations (following domain ownership):
- `cleanup_notification_logs` and `cleanup_notification_deliveries`: `backend/notifications/tasks.py`
- `cleanup_door_code_events`: `backend/locks/tasks.py` (new file)

### 3) Ensure tasks are visible in the scheduler status UI
Scheduler UI (ADR 0063) should show these tasks alongside existing ones by relying on the existing task registry and health/run tracking:

- Provide a clear `description=` in `@register(...)` so the UI can display purpose.
- Keep task names stable (for long-lived UI history and alerting rules).

Optional follow-up (not required to consider this ADR implemented):
- Add a `result`/`metrics` field to `SchedulerTaskRun` so the UI can display “deleted N rows” without reading logs.

## Alternatives Considered
- Rely on manual admin cleanup: simple but error-prone; tables still grow indefinitely in unattended deployments.
- Database partitioning/TTL: robust at scale but adds operational complexity and reduces UI-configurable retention.
- External cron job: works, but duplicates the in-process scheduler and reduces visibility in the scheduler UI.

## Consequences
- Database growth is bounded for these audit/outbox tables, reducing the risk of storage exhaustion and degraded query performance.
- Old notification and door-code history becomes unavailable past the retention window (defaults chosen to preserve recent debugging/audit value).
- Additional deletes increase write load briefly during the cleanup window; retention-based deletes should be indexed to remain efficient.

## Todos
- Add SystemConfig settings and UI wiring for the three retention keys.
- Add indexes for efficient range deletes (must be deployed BEFORE enabling cleanup tasks to avoid full table scans):
  - `NotificationLog`: add index on `created_at` (currently has no index).
  - `NotificationDelivery`: add composite index on `(status, created_at)` for the combined filter; currently has only `status` indexed individually.
  - `DoorCodeEvent`: already has `created_at` in composite indexes (`[door_code, created_at]`, `[event_type, created_at]`, `[user, created_at]`) — no action needed.
- Implement three cleanup tasks and ensure they are imported on startup so they register with the scheduler.
- Add tests for each cleanup task (disabled retention, boundary conditions, and "do not delete pending/sending deliveries").
- (Optional) Extend `SchedulerTaskRun` to store structured task results for UI display.
