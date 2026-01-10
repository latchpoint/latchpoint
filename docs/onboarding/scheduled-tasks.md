# Scheduled Tasks (Cron Jobs)

This document describes all scheduled tasks in the alarm system.

## Overview

The project uses a custom in-process task scheduler (`backend/scheduler/`) that runs within the web process. Tasks are registered using a decorator and execute on configurable schedules.

**Key features:**
- No external dependencies (no Redis, no Celery)
- Watchdog thread auto-restarts crashed tasks
- Supports daily schedules and interval-based polling
- Management commands for inspection and manual execution

## Task Types

### Cron-Style Tasks (Daily at Specific Time)
These run once per day at a fixed time. Use `DailyAt(hour, minute)`.

### Poll-Based Tasks (Fixed Interval)
These run repeatedly at fixed intervals. Use `Every(seconds, jitter)`.

---

## All Registered Tasks

### Cron-Style Tasks (Scheduled Cleanup)

| Task | Schedule | Location | Purpose |
|------|----------|----------|---------|
| `cleanup_old_events` | 3:00 AM | `alarm/tasks.py` | Deletes `AlarmEvent` records older than retention period |
| `cleanup_rule_action_logs` | 3:30 AM | `alarm/tasks.py` | Deletes `RuleActionLog` records older than retention period |
| `cleanup_expired_sessions` | 4:00 AM | `alarm/tasks.py` | Clears expired Django sessions (wraps `clearsessions`) |
| `cleanup_orphan_rule_entity_refs` | 4:30 AM | `alarm/tasks.py` | Removes `RuleEntityRef` rows pointing to deleted entities |
| `cleanup_frigate_detections` | Every 1 hour | `integrations_frigate/tasks.py` | Deletes old `FrigateDetection` records per retention setting |

### Poll-Based Tasks (Interval)

| Task | Schedule | Location | Purpose |
|------|----------|----------|---------|
| `sync_entity_states` | Every 5 min | `alarm/tasks.py` | Syncs entity states from Home Assistant, triggers rules on changes |
| `check_home_assistant` | Every 30 sec | `alarm/tasks.py` | Checks HA connectivity, broadcasts status changes to WebSocket |
| `broadcast_system_status` | Every 2 sec | `alarm/tasks.py` | Pushes integration status to WebSocket clients (excludes HA) |
| `process_due_rule_runtimes` | Every 5 sec | `alarm/tasks.py` | Executes rules scheduled via `schedule_rule_at` action |
| `notifications_send_pending` | Every 5 sec | `notifications/tasks.py` | Processes notification outbox with retry/backoff |

---

## Task Details

### cleanup_old_events
**Schedule:** Daily at 3:00 AM  
**Config:** `events.retention_days` (SystemConfig, default: 30 days)

Deletes alarm events older than the retention period. Events include state transitions, sensor triggers, and system events.

### cleanup_rule_action_logs
**Schedule:** Daily at 3:30 AM  
**Config:** `rule_logs.retention_days` (SystemConfig, default: 7 days)

Deletes rule action execution logs. These track when rules fired and what actions ran.

### cleanup_expired_sessions
**Schedule:** Daily at 4:00 AM

Wraps Django's `clearsessions` management command to remove expired session records from the database.

### cleanup_orphan_rule_entity_refs
**Schedule:** Daily at 4:30 AM

Cleans up `RuleEntityRef` rows that reference entities that no longer exist. Part of the rules engine optimization (ADR 0057).

### cleanup_frigate_detections
**Schedule:** Every 1 hour (±60s jitter)  
**Config:** `retention_seconds` in Frigate settings

Deletes Frigate detection records older than the configured retention. Only runs if Frigate integration is enabled.

### sync_entity_states
**Schedule:** Every 5 minutes (±30s jitter)  
**Config:** `entity_sync.interval_seconds` (SystemConfig, default: 300)

Polls Home Assistant for current entity states and updates local `Entity` records. Triggers rules if states changed. This is a fallback sync—real-time updates come via HA WebSocket subscription when available.

### check_home_assistant
**Schedule:** Every 30 seconds (±5s jitter)

Checks Home Assistant connectivity and broadcasts status changes to WebSocket clients. Separated from `broadcast_system_status` because HA checks are slower (network call).

### broadcast_system_status
**Schedule:** Every 2 seconds

Broadcasts integration status (MQTT, Z-Wave JS, Frigate, Zigbee2MQTT) to WebSocket clients. Excludes Home Assistant (handled by `check_home_assistant`).

### process_due_rule_runtimes
**Schedule:** Every 5 seconds (±1s jitter)

Processes rules with `scheduled_for` timestamps that are now due. Enables "for: N seconds" rule conditions to fire even without new integration events.

### notifications_send_pending
**Schedule:** Every 5 seconds (±1s jitter)

Processes the notification delivery outbox:
- Picks up pending deliveries due for sending
- Sends via the appropriate provider (HA, Pushbullet, Slack)
- Handles retries with exponential backoff
- Marks deliveries as sent or dead after max attempts

---

## Management Commands

```bash
# List all registered tasks
python manage.py list_tasks

# Show next scheduled run times
python manage.py task_schedule

# Run a task manually (useful for testing/debugging)
python manage.py run_task <task_name>

# Examples:
python manage.py run_task cleanup_old_events
python manage.py run_task sync_entity_states
```

Via Docker:
```bash
./scripts/docker-shell.sh
python manage.py list_tasks
python manage.py run_task cleanup_old_events
```

---

## Adding a New Task

1. Create or edit a `tasks.py` file in your Django app
2. Import the scheduler and register decorator:
   ```python
   from scheduler import DailyAt, Every, register
   ```
3. Decorate your function:
   ```python
   # Daily task
   @register("my_daily_task", schedule=DailyAt(hour=2, minute=30))
   def my_daily_task() -> int:
       # ... do work ...
       return count
   
   # Interval task
   @register("my_polling_task", schedule=Every(seconds=60, jitter=5))
   def my_polling_task() -> None:
       # ... do work ...
   ```
4. Import your tasks module in `apps.py` `ready()` method (see `alarm/apps.py` for example)

**Best practices:**
- Tasks should be idempotent (safe to run multiple times)
- Log meaningful output for observability
- Return counts or status dicts for monitoring
- Use jitter on interval tasks to avoid thundering herd
- Handle exceptions gracefully (scheduler logs but doesn't stop on errors)

---

## Configuration

### Environment Variables
- `SCHEDULER_ENABLED`: Set to `false` to disable all scheduled tasks (default: `true`)

### SystemConfig Settings
These can be changed at runtime via the API:
- `events.retention_days`: Alarm event retention (default: 30)
- `rule_logs.retention_days`: Rule action log retention (default: 7)
- `entity_sync.interval_seconds`: Entity sync interval (default: 300, set to 0 to disable)

---

## Architecture

See [ADR 0024: In-Process Task Scheduler](../adr/0024-in-process-task-scheduler.md) for design decisions.

**Key points:**
- Scheduler runs in the web process (no separate worker container)
- Each task runs in its own daemon thread
- Watchdog thread monitors and restarts crashed task threads
- No persistence—missed runs during downtime are not recovered
- Overlapping executions are prevented (if a task is still running when scheduled, the new run is skipped)
