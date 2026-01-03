# ADR-0024: In-Process Task Scheduler with Watchdog

## Status
**Implemented** (Phase 1 complete)

## Context
The project needs lightweight scheduled tasks (e.g., event cleanup, future maintenance jobs) without adding external infrastructure like Celery, Redis, or separate Docker services.

The current implementation in `backend/alarm/scheduler.py` provides a basic scheduler for the cleanup task. This ADR proposes extracting and generalizing that pattern into a reusable task scheduling framework.

### Requirements
1. **Cron-like scheduling**: Support for daily, hourly, or custom schedules
2. **Watchdog**: Auto-restart crashed task threads
3. **In-process**: Run within the web process (no extra containers)
4. **Configurable**: Enable/disable via settings or environment
5. **Observable**: Logging for task execution and failures
6. **Testable**: Tasks can be called directly in tests without scheduler

## Decision
Create a minimal in-process task scheduler at `backend/scheduler/` with:

### 1. Schedule Types
```python
# backend/scheduler/schedules.py
from dataclasses import dataclass

class Schedule:
    """Base class for schedules."""
    pass

@dataclass
class DailyAt(Schedule):
    """Run once daily at specified time (uses Django TIME_ZONE setting)."""
    hour: int = 3
    minute: int = 0

@dataclass
class Every(Schedule):
    """Run at fixed intervals."""
    seconds: int = 3600  # Default: hourly
    jitter: int = 0      # Optional random jitter in seconds to avoid thundering herd
```

### 2. Task Registry
```python
# backend/scheduler/registry.py
from dataclasses import dataclass
from typing import Callable
from .schedules import Schedule

@dataclass
class ScheduledTask:
    name: str
    func: Callable[[], None]
    schedule: Schedule
    enabled: bool = True

_tasks: dict[str, ScheduledTask] = {}

def register(name: str, schedule: Schedule, enabled: bool = True):
    """Decorator to register a scheduled task."""
    def decorator(func: Callable[[], None]):
        _tasks[name] = ScheduledTask(name=name, func=func, schedule=schedule, enabled=enabled)
        return func
    return decorator

def get_tasks() -> dict[str, ScheduledTask]:
    return _tasks.copy()
```

### 3. Task Runner with Watchdog
```python
# backend/scheduler/runner.py
import threading
import time
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from .registry import get_tasks, ScheduledTask
from .schedules import DailyAt, Every, Schedule

logger = logging.getLogger(__name__)

_WATCHDOG_INTERVAL = 60  # Check threads every 60 seconds
_lock = threading.Lock()  # Protect shared state
_threads: dict[str, threading.Thread] = {}
_running: set[str] = set()  # Track currently executing tasks
_watchdog_started = False

def _compute_next_run(schedule: Schedule, now: datetime) -> datetime:
    """Compute next run time for a schedule."""
    import random

    if isinstance(schedule, DailyAt):
        next_run = now.replace(hour=schedule.hour, minute=schedule.minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run
    elif isinstance(schedule, Every):
        jitter = random.randint(0, schedule.jitter) if schedule.jitter > 0 else 0
        return now + timedelta(seconds=schedule.seconds + jitter)
    raise ValueError(f"Unknown schedule type: {type(schedule)}")

def _run_task_loop(task: ScheduledTask) -> None:
    """Run a task on its schedule forever."""
    while True:
        now = timezone.now()
        next_run = _compute_next_run(task.schedule, now)
        sleep_seconds = (next_run - now).total_seconds()

        logger.info("Task %s scheduled for %s (in %.0fs)", task.name, next_run.isoformat(), sleep_seconds)
        time.sleep(max(0, sleep_seconds))

        # Prevent overlapping executions
        with _lock:
            if task.name in _running:
                logger.warning("Task %s still running, skipping this execution", task.name)
                continue
            _running.add(task.name)

        start_time = time.monotonic()
        try:
            logger.info("Task %s starting", task.name)
            task.func()
            duration = time.monotonic() - start_time
            logger.info("Task %s completed in %.2fs", task.name, duration)
        except Exception:
            logger.exception("Task %s failed after %.2fs", task.name, time.monotonic() - start_time)
        finally:
            with _lock:
                _running.discard(task.name)

def _run_watchdog() -> None:
    """Monitor task threads and restart any that died."""
    while True:
        time.sleep(_WATCHDOG_INTERVAL)

        for name, task in get_tasks().items():
            if not task.enabled:
                continue

            with _lock:
                thread = _threads.get(name)
                if thread is None or not thread.is_alive():
                    if thread is not None:
                        logger.warning("Task %s thread died, restarting...", name)

                    new_thread = threading.Thread(
                        target=_run_task_loop,
                        args=(task,),
                        name=f"task-{name}",
                        daemon=True,
                    )
                    new_thread.start()
                    _threads[name] = new_thread
                    logger.info("Started task thread: %s", name)

def start_scheduler() -> None:
    """Start all registered tasks and the watchdog."""
    global _watchdog_started

    with _lock:
        if _watchdog_started:
            return
        _watchdog_started = True  # Set early to prevent race conditions

        # Start task threads
        for name, task in get_tasks().items():
            if not task.enabled:
                continue
            thread = threading.Thread(
                target=_run_task_loop,
                args=(task,),
                name=f"task-{name}",
                daemon=True,
            )
            thread.start()
            _threads[name] = thread
            logger.info("Started task thread: %s", name)

    # Start watchdog (outside lock - it will acquire lock when needed)
    watchdog = threading.Thread(
        target=_run_watchdog,
        name="task-watchdog",
        daemon=True,
    )
    watchdog.start()
    logger.info("Started task watchdog")
```

### 4. Task Definition Example
```python
# backend/alarm/tasks.py
from scheduler import register, DailyAt

@register("cleanup_old_events", schedule=DailyAt(hour=3, minute=0))
def cleanup_old_events() -> int:
    """Delete old events."""
    ...
```

### 5. App Startup
```python
# backend/scheduler/apps.py
import sys
from django.apps import AppConfig
from django.conf import settings

def _should_start() -> bool:
    """Determine if the scheduler should start in this process."""
    # Check settings flag
    if not getattr(settings, 'SCHEDULER_ENABLED', True):
        return False

    # Don't start during migrations, shell, or other management commands
    if len(sys.argv) > 1:
        command = sys.argv[1]
        allowed_commands = {'runserver', 'run'}
        if command not in allowed_commands:
            return False

    # Check for gunicorn/uvicorn (production WSGI/ASGI servers)
    if 'gunicorn' in sys.argv[0] or 'uvicorn' in sys.argv[0]:
        return True

    return 'runserver' in sys.argv

class SchedulerConfig(AppConfig):
    name = "scheduler"

    def ready(self):
        if _should_start():
            # Import tasks to trigger registration
            import alarm.tasks  # noqa

            from .runner import start_scheduler
            start_scheduler()
```

### 6. Management Commands
```python
# List registered tasks
python manage.py list_tasks

# Run a task manually
python manage.py run_task cleanup_old_events

# Show next scheduled runs
python manage.py task_schedule
```

## Directory Structure
```
backend/
└── scheduler/
    ├── __init__.py       # Public API exports
    ├── apps.py           # Django app config
    ├── registry.py       # Task registration
    ├── runner.py         # Scheduler + watchdog
    ├── schedules.py      # Schedule types (DailyAt, Every, Cron)
    └── management/
        └── commands/
            ├── list_tasks.py
            ├── run_task.py
            └── task_schedule.py
```

## Configuration

```python
# backend/config/settings.py

# Enable/disable the scheduler (default: True)
SCHEDULER_ENABLED = env.bool("SCHEDULER_ENABLED", default=True)

# Timezone for DailyAt schedules (default: server timezone via USE_TZ)
# Tasks use Django's timezone.now() which respects TIME_ZONE setting
```

## Schedule Types

### Phase 1 (MVP)
- `DailyAt(hour, minute)` - Run once daily at specified time (uses Django's TIME_ZONE)
- `Every(seconds)` - Run at fixed intervals

### Phase 2 (Future)
- `Cron(expression)` - Full cron expression support
- `Weekly(day, hour, minute)` - Run once per week
- `Monthly(day, hour, minute)` - Run once per month

## Behavior

### Initial Run
Tasks do **not** run immediately on startup. They wait for their first scheduled time. If immediate execution is needed, use management commands:
```bash
python manage.py run_task cleanup_old_events
```

### Overlapping Executions
If a task is still running when its next scheduled time arrives, the execution is skipped and logged as a warning. This prevents resource exhaustion from long-running tasks.

### Graceful Shutdown
Daemon threads are used, so threads are terminated when the main process exits. For tasks requiring cleanup, use signal handlers:
```python
import signal

def _handle_shutdown(signum, frame):
    logger.info("Scheduler shutting down...")
    # Tasks should check a shutdown flag periodically for long operations

signal.signal(signal.SIGTERM, _handle_shutdown)
```

## Observability

### Logging
All task lifecycle events are logged:
- Task scheduled (with next run time)
- Task started
- Task completed (with duration)
- Task failed (with exception details)
- Thread restart by watchdog

### Health Check (Phase 2)
```python
# backend/scheduler/health.py
def get_scheduler_status() -> dict:
    """Return scheduler health for monitoring endpoints."""
    return {
        "running": _watchdog_started,
        "tasks": {
            name: {
                "thread_alive": _threads.get(name, None) is not None
                                and _threads[name].is_alive(),
                "currently_running": name in _running,
            }
            for name in get_tasks()
        }
    }
```

### Metrics (Phase 2)
Consider adding prometheus-style metrics:
- `scheduler_task_runs_total{task="name", status="success|failure"}`
- `scheduler_task_duration_seconds{task="name"}`
- `scheduler_task_skipped_total{task="name"}` (overlapping executions)

## Alternatives Considered

### django-tasks (Django 6.0+)
- **Pros**: First-party, database-backed queue
- **Cons**: Requires separate worker process, more complex
- **Verdict**: Overkill for simple scheduled tasks

### APScheduler
- **Pros**: Feature-rich, battle-tested
- **Cons**: Another dependency, may be heavyweight
- **Verdict**: Consider if requirements grow significantly

### Celery Beat
- **Pros**: Industry standard, very powerful
- **Cons**: Requires Redis/RabbitMQ, separate processes
- **Verdict**: Too heavy for current needs

### External cron
- **Pros**: Simple, well-understood
- **Cons**: Requires container/host configuration, not portable
- **Verdict**: Fallback option via management commands

## Consequences

### Positive
- Zero external dependencies
- No extra Docker services
- Self-healing via watchdog
- Simple decorator-based task registration
- Management commands for debugging
- Easy to test (call task functions directly)

### Negative
- Scheduler lifecycle tied to web process
- No persistence (missed runs during downtime aren't recovered)
- No distributed locking (assumes single web instance)
- Limited schedule expressiveness vs full cron

### Mitigations
- For missed runs: Tasks should be idempotent and catch up on next run
- For multi-instance: Add optional Redis-based locking in Phase 2
- For complex schedules: Add Cron schedule type in Phase 2

## Migration Path
1. Create `backend/core/scheduler/` with registry and runner
2. Migrate `backend/alarm/scheduler.py` to use new framework
3. Update `backend/alarm/tasks.py` to use `@register` decorator
4. Remove `backend/alarm/scheduler.py`
5. Add management commands

## Todos

### Phase 1 (MVP) - Completed
- [x] Create `backend/scheduler/` package
- [x] Implement `schedules.py` with DailyAt and Every
- [x] Implement `registry.py` with task registration
- [x] Implement `runner.py` with scheduler, watchdog, and thread safety
- [x] Implement `apps.py` with `_should_start()` logic
- [x] Create `list_tasks` management command
- [x] Create `run_task` management command
- [x] Create `task_schedule` management command
- [x] Migrate cleanup_old_events to new framework
- [x] Remove `backend/alarm/scheduler.py`
- [x] Add tests for scheduler framework
- [x] Document in AGENTS.md

### Phase 2 (Future)
- [x] Add `get_scheduler_status()` for monitoring (included in runner.py)
- [ ] Add Prometheus-style metrics
- [ ] Add `Cron(expression)` schedule type
- [ ] Add optional Redis-based distributed locking
