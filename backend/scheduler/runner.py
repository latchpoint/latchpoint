"""Task runner with watchdog for the scheduler."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta

from django.utils import timezone

from .registry import ScheduledTask, get_tasks
from .schedules import DailyAt, Every, Schedule

logger = logging.getLogger(__name__)

_WATCHDOG_INTERVAL = 60  # Check threads every 60 seconds
_lock = threading.Lock()  # Protect shared state
_threads: dict[str, threading.Thread] = {}
_running: set[str] = set()  # Track currently executing tasks
_watchdog_started = False


def _compute_next_run(schedule: Schedule, now: datetime) -> datetime:
    """Compute next run time for a schedule."""
    if isinstance(schedule, DailyAt):
        next_run = now.replace(
            hour=schedule.hour,
            minute=schedule.minute,
            second=0,
            microsecond=0,
        )
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

        logger.info(
            "Task %s scheduled for %s (in %.0fs)",
            task.name,
            next_run.isoformat(),
            sleep_seconds,
        )
        time.sleep(max(0, sleep_seconds))

        # Prevent overlapping executions
        with _lock:
            if task.name in _running:
                logger.warning(
                    "Task %s still running, skipping this execution",
                    task.name,
                )
                continue
            _running.add(task.name)

        start_time = time.monotonic()
        try:
            logger.info("Task %s starting", task.name)
            task.func()
            duration = time.monotonic() - start_time
            logger.info("Task %s completed in %.2fs", task.name, duration)
        except Exception:
            logger.exception(
                "Task %s failed after %.2fs",
                task.name,
                time.monotonic() - start_time,
            )
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


def get_scheduler_status() -> dict:
    """Return scheduler health for monitoring endpoints."""
    with _lock:
        return {
            "running": _watchdog_started,
            "tasks": {
                name: {
                    "thread_alive": _threads.get(name) is not None
                    and _threads[name].is_alive(),
                    "currently_running": name in _running,
                }
                for name in get_tasks()
            },
        }
