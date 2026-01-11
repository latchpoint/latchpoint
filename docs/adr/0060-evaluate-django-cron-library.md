# ADR 0060: Evaluate django-cron Library vs Custom Scheduler

## Status
Superseded

## Context
The project currently uses a custom in-process task scheduler (`backend/scheduler/`) implemented in ADR-0024. This scheduler provides:

- Decorator-based task registration (`@register`)
- Schedule types: `DailyAt(hour, minute)` and `Every(seconds, jitter)`
- Watchdog thread to restart crashed task threads
- Management commands: `list_tasks`, `run_task`, `task_schedule`
- No external dependencies (runs in-process with web server)

### Current Tasks (10 registered)
| Task | Schedule | Purpose |
|------|----------|---------|
| `cleanup_old_events` | Daily 3:00 | Delete old alarm events |
| `cleanup_rule_action_logs` | Daily 3:30 | Delete old rule action logs |
| `cleanup_expired_sessions` | Daily 4:00 | Clear expired Django sessions |
| `cleanup_orphan_rule_entity_refs` | Daily 4:30 | Remove stale rule entity refs |
| `cleanup_frigate_detections` | Every 1h | Delete old Frigate detections |
| `sync_entity_states` | Every 5m | Sync entity states from integrations |
| `broadcast_system_status` | Every 2s | Push integration status to WS clients |
| `check_home_assistant` | Every 30s | Check HA connectivity |
| `process_due_rule_runtimes` | Every 5s | Execute scheduled rules |
| `notifications_send_pending` | Every 5s | Process notification outbox |

### Pain Points with Current Implementation
1. **No persistence**: Tasks don’t “catch up” after downtime (mostly relevant to daily/hourly maintenance jobs; less relevant to 2–5s loops)
2. **No execution history**: No built-in tracking of task runs/failures in DB
3. **Custom code**: ~330 LOC to maintain (registry, runner, schedules, app config)
4. **Limited schedule types**: Only daily-at and fixed-interval schedules
5. **No admin visibility**: Requires CLI/logs to inspect task status

### Why Evaluate django-cron
The `django-cron` library is a mature, well-tested package that provides cron-like scheduling with Django integration. It offers:

- Database-backed execution history
- Admin interface for monitoring
- Django-friendly configuration (per-job classes)

## Decision
This ADR is deprecated. Given the constraint of not adding new Docker Compose services, we are not pursuing Celery/beat, and `django-cron` does not meet the project’s sub-minute scheduling needs. We will keep the custom in-process scheduler for now; any future scheduler replacement should be captured in a new ADR with the updated constraints and target architecture.

Target end state:
- Periodic work runs outside the web request/ASGI process (no watchdog threads inside Daphne/Gunicorn workers).
- Task execution has persistence/visibility (DB-backed schedules + run history, admin UI).
- The custom scheduler (`backend/scheduler/`) is deleted.

Near-term plan:
- Move daily/hourly/minutely maintenance tasks off the custom scheduler first.
- Keep the custom scheduler temporarily only for sub-minute loops until they are redesigned (event-driven or queue-based).

This ADR keeps `django-cron` in scope as an incremental step, but prioritizes a more popular, long-term replacement: **Celery + django-celery-beat**.

### django-cron Overview
- **PyPI**: https://pypi.org/project/django-cron/
- **GitHub**: https://github.com/Tivix/django-cron
- **License**: MIT

### Feature Comparison

| Feature | Custom Scheduler | django-cron |
|---------|------------------|-------------|
| In-process execution | ✅ | ✅ |
| Database persistence | ❌ | ✅ |
| Execution history/logs | ❌ | ✅ (via `CronJobLog`) |
| Admin visibility | ❌ | ✅ (via Django admin if enabled) |
| Cron expressions | ❌ | ⚠️ No (cron-like: times + minute intervals) |
| Interval schedules | ✅ (`Every` in seconds) | ✅ (minute granularity) |
| Daily schedules | ✅ (`DailyAt`) | ✅ |
| Jitter support | ✅ | ❌ |
| Watchdog/auto-restart | ✅ | ❌ |
| Overlap prevention | ✅ (per-process) | ✅ (DB lock) |
| Multi-process safety | ❌ (runs once per process) | ✅ (DB lock, assuming a single `runcrons` trigger) |
| Manual job execution | ✅ (`manage.py run_task`) | ✅ (`MyCronJob().do()` or `runcrons --force`) |
| Run all jobs | ✅ (automatic on startup) | ✅ (`manage.py runcrons`) |
| Dependencies | None | django-cron package |

### Most Popular Django Option
In the Django ecosystem, the most common choice for periodic tasks is:
- **Celery + django-celery-beat** (admin-managed schedules, durable broker-backed execution)

That comes with operational costs (broker + worker process), but it aligns with the long-term goal of removing the in-process watchdog scheduler.

### Manual Job Execution in django-cron
django-cron supports running jobs manually:

```python
# Programmatically call the do() method
from myapp.cron import MyCronJob
MyCronJob().do()

# Or via management command (runs all due jobs)
python manage.py runcrons

# Force run even if not due
python manage.py runcrons --force
```

### Migration Mapping

Current decorator:
```python
@register("cleanup_old_events", schedule=DailyAt(hour=3, minute=0))
def cleanup_old_events() -> int:
    ...
```

django-cron equivalent:
```python
from django_cron import CronJobBase, Schedule

class CleanupOldEventsCronJob(CronJobBase):
    RUN_AT_TIMES = ['03:00']
    schedule = Schedule(run_at_times=RUN_AT_TIMES)
    code = 'alarm.cleanup_old_events'

    def do(self):
        ...
```

For interval-based tasks:
```python
class BroadcastSystemStatusCronJob(CronJobBase):
    # Not supported at 2s; minimum is 1 minute.
    schedule = Schedule(run_every_mins=1)
    code = 'alarm.broadcast_system_status'
```

### Critical Limitation: Sub-Minute Scheduling
**django-cron does not support sub-minute intervals.** The minimum schedule is 1 minute.

Current tasks requiring sub-minute execution:
- `broadcast_system_status`: Every 2 seconds
- `process_due_rule_runtimes`: Every 5 seconds
- `notifications_send_pending`: Every 5 seconds

These tasks cannot be migrated to django-cron without architectural changes.

### Task Migration Suitability

| Task | Schedule | django-cron Compatible | Notes |
|------|----------|------------------------|-------|
| `cleanup_old_events` | Daily 3:00 AM | ✅ Yes | Ideal candidate - daily cleanup |
| `cleanup_rule_action_logs` | Daily 3:30 AM | ✅ Yes | Ideal candidate - daily cleanup |
| `cleanup_expired_sessions` | Daily 4:00 AM | ✅ Yes | Ideal candidate - daily cleanup |
| `cleanup_orphan_rule_entity_refs` | Daily 4:30 AM | ✅ Yes | Ideal candidate - daily cleanup |
| `cleanup_frigate_detections` | Every 1 hour | ✅ Yes | `RUN_EVERY_MINS=60` works |
| `sync_entity_states` | Every 5 min | ✅ Yes | `RUN_EVERY_MINS=5` works |
| `check_home_assistant` | Every 30 sec | ❌ No | Sub-minute, needs custom scheduler |
| `broadcast_system_status` | Every 2 sec | ❌ No | Sub-minute, needs custom scheduler |
| `process_due_rule_runtimes` | Every 5 sec | ❌ No | Sub-minute, needs custom scheduler |
| `notifications_send_pending` | Every 5 sec | ❌ No | Sub-minute, needs custom scheduler |

**Summary:** 6 of 10 tasks could use django-cron; 4 require the custom scheduler due to sub-minute intervals.

### Execution Model Difference
- **Custom scheduler**: Runs continuously in-process with threads
- **django-cron**: Requires something to invoke `manage.py runcrons` periodically (commonly a system cron entry or a systemd timer)

This means django-cron would require:
1. A cron job or systemd timer to call `runcrons` every minute
2. Or a wrapper script/loop to call it continuously

### Operational Consideration: Per-Process Scheduling
The current scheduler starts inside each web process. If the deployment ever runs multiple Daphne/Gunicorn workers or multiple app replicas, each process will start its own scheduler threads and execute tasks independently.

- Today this is mitigated by overlap prevention only within a single process.
- If/when we scale beyond a single process/replica, we’ll need cross-process coordination (e.g., Postgres advisory lock leader election, or DB-backed per-task locks).

## Alternatives Considered

### 1. Keep Custom Scheduler (Current)
- **Pros**: Already working, supports sub-minute tasks, no dependencies
- **Cons**: No persistence, no admin UI, per-process duplication risk when scaled

### 2. django-cron
- **Pros**: Mature, database persistence, admin UI
- **Cons**: No sub-minute support, requires external trigger (`runcrons`), not the most common Django stack

### 3. APScheduler
- **Pros**: Feature-rich, sub-minute support, in-process
- **Cons**: Another dependency, more complex API

### 4. Celery Beat
- **Pros**: Industry standard, very powerful, sub-minute support
- **Cons**: Requires Redis/RabbitMQ, separate worker process

### 5. Hybrid Approach
Keep custom scheduler for sub-minute tasks, use django-cron for daily/hourly tasks.
- **Pros**: Best of both worlds
- **Cons**: Two systems to maintain, increased complexity

### 6. django-background-tasks
- **Pros**: Database-backed, no external broker
- **Cons**: Designed for one-off tasks, not ideal for recurring schedules

## Recommendation
**Migrate away from the custom scheduler in phases.**

1) **Primary recommendation (long-term):** adopt **Celery + django-celery-beat** and move cron-like maintenance work there first.
2) **Optional interim step:** use `django-cron` for cron-like tasks only if we explicitly want a “no broker” stopgap and accept its trigger model.

### Rationale
1. **Goal alignment**: The custom scheduler runs inside the web process and scales poorly; the end goal is to remove it.
2. **Popularity/maintainability**: Celery + beat is the most common Django scheduling approach with strong ecosystem support.
3. **Phased risk reduction**: Migrating low-frequency maintenance tasks first is safer than tackling sub-minute loops immediately.
4. **Sub-minute tasks need redesign anyway**: The 2–5s loops are better handled via event-driven triggering, queue workers, or long-running services rather than “cron”.

### If Persistence Is Needed Later
If execution history/persistence becomes a requirement, consider:
1. Prefer solving it by moving tasks to Celery/beat (beats logs + app-level logging/metrics).
2. If we keep the custom scheduler temporarily, add DB-backed `TaskRun` logging and cross-process coordination (e.g., Postgres advisory lock leader election).

## Consequences

### Positive
- Clear path to deleting the in-process watchdog scheduler
- Cron-like maintenance tasks can move first (lowest risk)

### Negative
- For Celery/beat: requires adding a broker + worker process to the deployment architecture
- For any phased approach: two systems exist temporarily until sub-minute loops are redesigned and migrated
- No admin interface for task monitoring

### Mitigations
- Add `TaskExecutionLog` model if history is needed (simple addition to custom scheduler)
- Use `manage.py task_schedule` and logs for monitoring

## Todos
- [ ] Document this analysis for future reference
- [ ] Consider adding `TaskExecutionLog` model if execution history becomes a requirement
- [ ] Re-evaluate if requirements change (e.g., need for distributed execution)
