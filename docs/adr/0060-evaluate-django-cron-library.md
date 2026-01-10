# ADR 0060: Evaluate django-cron Library vs Custom Scheduler

## Status
Proposed

## Context
The project currently uses a custom in-process task scheduler (`backend/scheduler/`) implemented in ADR-0024. This scheduler provides:

- Decorator-based task registration (`@register`)
- Schedule types: `DailyAt(hour, minute)` and `Every(seconds, jitter)`
- Watchdog thread to restart crashed task threads
- Management commands: `list_tasks`, `run_task`, `task_schedule`
- No external dependencies (runs in-process with web server)

### Current Tasks (11 registered)
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
1. **No persistence**: Missed runs during downtime aren't recovered
2. **No execution history**: No built-in tracking of task runs/failures
3. **Custom code**: ~200 LOC to maintain (registry, runner, schedules)
4. **Limited schedule types**: No full cron expressions (e.g., "every Monday at 9am")
5. **No admin visibility**: Requires CLI to inspect task status

### Why Evaluate django-cron
The `django-cron` library is a mature, well-tested package that provides cron-like scheduling with Django integration. It offers:

- Database-backed execution history
- Admin interface for monitoring
- Cron expression support
- Built-in retry/failure handling

## Decision
Evaluate `django-cron` as a potential replacement for the custom scheduler. This ADR documents the analysis and recommendation.

### django-cron Overview
- **PyPI**: https://pypi.org/project/django-cron/
- **GitHub**: https://github.com/Tivix/django-cron
- **License**: MIT

### Feature Comparison

| Feature | Custom Scheduler | django-cron |
|---------|------------------|-------------|
| In-process execution | ✅ | ✅ |
| Database persistence | ❌ | ✅ |
| Execution history/logs | ❌ | ✅ |
| Admin interface | ❌ | ✅ |
| Cron expressions | ❌ | ✅ |
| Interval schedules | ✅ (`Every`) | ✅ |
| Daily schedules | ✅ (`DailyAt`) | ✅ |
| Jitter support | ✅ | ❌ |
| Watchdog/auto-restart | ✅ | ❌ |
| Overlap prevention | ✅ | ✅ |
| Manual job execution | ✅ (`manage.py run_task`) | ✅ (`MyCronJob().do()` or `runcrons --force`) |
| Run all jobs | ✅ (automatic on startup) | ✅ (`manage.py runcrons`) |
| Dependencies | None | django-cron package |

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
    RUN_EVERY_MINS = 0  # Not supported - minimum is 1 minute
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
- **django-cron**: Requires external cron to call `manage.py runcrons` periodically

This means django-cron would require:
1. A cron job or systemd timer to call `runcrons` every minute
2. Or a wrapper script/loop to call it continuously

## Alternatives Considered

### 1. Keep Custom Scheduler (Current)
- **Pros**: Already working, supports sub-minute tasks, no dependencies
- **Cons**: No persistence, no admin UI, custom code to maintain

### 2. django-cron
- **Pros**: Mature, database persistence, admin UI
- **Cons**: No sub-minute support, requires external cron trigger

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
**Do not migrate to django-cron.** The critical limitation of no sub-minute scheduling makes it unsuitable for this project's needs.

### Rationale
1. **Sub-minute tasks are essential**: Real-time features (system status broadcast, rule processing, notifications) require 2-5 second intervals.
2. **Migration complexity**: Would need to maintain two systems (django-cron for daily tasks, custom for sub-minute).
3. **Current solution works**: The custom scheduler is stable, tested, and meets requirements.
4. **Low maintenance burden**: ~200 LOC is manageable and well-understood.

### If Persistence Is Needed Later
If execution history/persistence becomes a requirement, consider:
1. Adding a simple `TaskRun` model to log executions in the custom scheduler
2. Evaluating APScheduler with its job stores feature
3. Moving to Celery Beat when the project needs distributed task execution

## Consequences

### Positive
- No migration effort required
- No new dependencies
- Sub-minute tasks continue to work

### Negative
- No built-in execution history (can be added if needed)
- No admin interface for task monitoring

### Mitigations
- Add `TaskExecutionLog` model if history is needed (simple addition to custom scheduler)
- Use `manage.py task_schedule` and logs for monitoring

## Todos
- [ ] Document this analysis for future reference
- [ ] Consider adding `TaskExecutionLog` model if execution history becomes a requirement
- [ ] Re-evaluate if requirements change (e.g., need for distributed execution)
