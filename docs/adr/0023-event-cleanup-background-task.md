# ADR-0023: Event Cleanup Background Task

## Status
**Implemented**

## Context
The `AlarmEvent` model stores an append-only log of all alarm activity (state changes, sensor triggers, code entries, etc.). Over time this table will grow unbounded, degrading query performance and consuming storage.

A system config setting `events.retention_days` (default: 30) already exists in `backend/alarm/settings_registry.py` but has no implementation that enforces it.

## Decision
Implement an in-process background scheduler that:

1. **Deletes `AlarmEvent` records** older than the configured retention period
2. **Runs daily at 3 AM** within the web process (no separate service needed)
3. **Respects the `events.retention_days` system config** setting (UI-editable)
4. **Includes a watchdog** that restarts the scheduler thread if it dies
5. **Logs the count of deleted records** for observability

### Implementation

#### 1. Task function
Location: `backend/alarm/tasks.py`

```python
def cleanup_old_events() -> int:
    """Delete AlarmEvent records older than the configured retention period."""
    retention_days = _get_retention_days()
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted_count, _ = AlarmEvent.objects.filter(timestamp__lt=cutoff).delete()
    return deleted_count
```

#### 2. Scheduler with watchdog
Location: `backend/alarm/scheduler.py`

- Scheduler thread runs daily at 3 AM
- Watchdog thread checks every 60 seconds and restarts scheduler if dead
- Only starts in web process (daphne/runserver), not during tests/migrations

```python
def _run_cleanup_scheduler() -> None:
    while True:
        # Sleep until 3 AM
        now = timezone.now()
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        time.sleep((next_run - now).total_seconds())
        
        # Run cleanup
        cleanup_old_events()

def _run_watchdog() -> None:
    while True:
        time.sleep(60)
        if scheduler_thread is None or not scheduler_thread.is_alive():
            # Restart scheduler thread
            ...
```

#### 3. App startup
Location: `backend/alarm/apps.py`

```python
def ready(self) -> None:
    from .scheduler import start_cleanup_scheduler
    start_cleanup_scheduler()
```

#### 4. Management command
Location: `backend/alarm/management/commands/cleanup_events.py`

```python
def handle(self, *args, **options):
    deleted = cleanup_old_events()
    self.stdout.write(f"Deleted {deleted} old events")
```

#### 5. UI configuration
Location: `frontend/src/features/alarmSettings/components/SystemSettingsCard.tsx`

Added to the Alarm settings tab, allowing admins to configure event retention (1-365 days).

## Alternatives Considered

### django-tasks / Celery
- **Pros**: Battle-tested, rich scheduling features
- **Cons**: Additional service/infrastructure, heavier dependency
- **Verdict**: Overkill for a single daily cleanup job

### Cron in separate container
- **Pros**: Standard approach, container isolation
- **Cons**: Extra container to manage
- **Verdict**: Unnecessary complexity for this use case

### Database-level TTL / partitioning
- **Pros**: Automatic, zero application code
- **Cons**: PostgreSQL-specific, harder to configure from UI
- **Verdict**: Good for high-volume systems but less flexible

## Consequences

### Positive
- Events table stays bounded, maintaining query performance
- Retention is UI-configurable without code changes
- No extra Docker services needed—runs in the web process
- Watchdog provides self-healing if scheduler thread crashes
- Management command provides manual/debugging escape hatch

### Negative
- Scheduler is coupled to web process lifecycle
- If web process restarts at 3 AM, cleanup may run twice or be delayed

## Files Changed
- `backend/alarm/tasks.py` (new)
- `backend/alarm/scheduler.py` (new)
- `backend/alarm/apps.py` (start scheduler)
- `backend/alarm/management/commands/cleanup_events.py` (new)
- `backend/alarm/tests/test_cleanup_events.py` (new)
- `frontend/src/features/alarmSettings/components/SystemSettingsCard.tsx` (new)
- `frontend/src/pages/settings/SettingsAlarmTab.tsx` (import SystemSettingsCard)
