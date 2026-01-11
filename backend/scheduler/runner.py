"""Task runner with watchdog for the scheduler."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.db import close_old_connections
from django.db import connection
from django.utils import timezone

from .registry import ScheduledTask, evaluate_task_enabled, get_tasks
from .schedules import DailyAt, Every, Schedule

logger = logging.getLogger(__name__)

_WATCHDOG_INTERVAL = 60  # Check threads every 60 seconds
_lock = threading.Lock()  # Protect shared state
_threads: dict[str, threading.Thread] = {}
_stop_events: dict[str, threading.Event] = {}
_running: set[str] = set()  # Track currently executing tasks
_watchdog_started = False
_task_status: dict[str, dict[str, object]] = {}
_leader_lock_acquired = False
_leader_lock_error: str | None = None


def _compute_next_run(schedule: Schedule, now: datetime) -> datetime:
    """Compute next run time for a schedule."""
    if isinstance(schedule, DailyAt):
        local_now = timezone.localtime(now)
        next_run = local_now.replace(
            hour=schedule.hour,
            minute=schedule.minute,
            second=0,
            microsecond=0,
        )
        if next_run <= local_now:
            next_run += timedelta(days=1)
        return next_run
    elif isinstance(schedule, Every):
        jitter_offset = (
            random.randint(-schedule.jitter, schedule.jitter) if schedule.jitter > 0 else 0
        )
        delay_seconds = max(0, schedule.seconds + jitter_offset)
        return now + timedelta(seconds=delay_seconds)
    raise ValueError(f"Unknown schedule type: {type(schedule)}")


def _failure_delay_seconds(*, task: ScheduledTask, consecutive_failures: int) -> tuple[int, bool]:
    """
    Return (delay_seconds, is_suspended) based on task failure policy.

    Delay is applied as a minimum "not before" time, never as an earlier retry.
    """
    consecutive_failures = max(0, int(consecutive_failures))
    if consecutive_failures <= 0:
        return 0, False

    delay_seconds = 0
    if task.failure_backoff_base_seconds > 0:
        delay_seconds = int(task.failure_backoff_base_seconds * (2 ** (consecutive_failures - 1)))
        if task.failure_backoff_max_seconds > 0:
            delay_seconds = min(delay_seconds, int(task.failure_backoff_max_seconds))

    is_suspended = False
    if (
        task.failure_suspend_after > 0
        and consecutive_failures >= task.failure_suspend_after
        and task.failure_suspend_seconds > 0
    ):
        delay_seconds = max(delay_seconds, int(task.failure_suspend_seconds))
        is_suspended = True

    return max(0, int(delay_seconds)), is_suspended


def _task_enabled_now(task: ScheduledTask) -> tuple[bool, str | None]:
    """
    Return (enabled_now, reason).

    This must be side-effect free (no network IO). Predicates may read cached state/DB.
    """
    enabled, reason = evaluate_task_enabled(task)
    return bool(enabled), reason


def _maybe_acquire_leader_lock() -> bool:
    """
    Best-effort leader lock for multi-process deployments (Postgres only).

    In local single-process setups this is typically disabled.
    """
    global _leader_lock_acquired
    global _leader_lock_error

    if not bool(getattr(settings, "SCHEDULER_LEADER_LOCK_ENABLED", False)):
        _leader_lock_acquired = True
        _leader_lock_error = None
        return True

    try:
        if connection.vendor != "postgresql":
            _leader_lock_acquired = True
            _leader_lock_error = None
            logger.info(
                "Scheduler leader lock enabled but DB is %s; skipping lock",
                connection.vendor,
            )
            return True

        lock_id = int(getattr(settings, "SCHEDULER_LEADER_LOCK_ID", 4242001))
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_id])
            acquired = bool(cursor.fetchone()[0])
        _leader_lock_acquired = acquired
        _leader_lock_error = None
        if not acquired:
            logger.warning("Scheduler leader lock not acquired; scheduler will not start")
        return acquired
    except Exception as exc:
        _leader_lock_acquired = False
        _leader_lock_error = str(exc)
        logger.exception("Scheduler leader lock acquisition failed; scheduler will not start")
        return False

def _run_task_loop(*, task: ScheduledTask, stop_event: threading.Event) -> None:
    """Run a task on its schedule forever."""
    try:
        from . import telemetry

        telemetry.touch_task_health_registered(task=task)
    except Exception:
        pass

    while True:
        if stop_event.is_set():
            logger.info("Task %s stopping (disabled/gated)", task.name)
            with _lock:
                _task_status.setdefault(task.name, {})
                _task_status[task.name].update({"next_run_at": None, "stopping": False})
            return

        close_old_connections()
        now = timezone.now()
        next_run = _compute_next_run(task.schedule, now)

        with _lock:
            consecutive_failures = int((_task_status.get(task.name, {}).get("consecutive_failures") or 0))

        delay_seconds, is_suspended = _failure_delay_seconds(
            task=task,
            consecutive_failures=consecutive_failures,
        )
        if delay_seconds > 0:
            not_before = now + timedelta(seconds=delay_seconds)
            next_run = max(next_run, not_before)
            with _lock:
                status = _task_status.setdefault(task.name, {})
                status["backoff_until_at"] = not_before.isoformat()
                status["backoff_seconds"] = delay_seconds
                status["suspended"] = bool(is_suspended)

        sleep_seconds = (next_run - now).total_seconds()

        with _lock:
            _task_status.setdefault(task.name, {})
            _task_status[task.name].update(
                {
                    "next_run_at": next_run.isoformat(),
                    "last_scheduled_at": now.isoformat(),
                }
            )

        try:
            from . import telemetry

            telemetry.update_task_health_scheduling(task=task, next_run_at=next_run)
        except Exception:
            pass

        logger.info(
            "Task %s scheduled for %s (in %.0fs)",
            task.name,
            next_run.isoformat(),
            sleep_seconds,
        )
        stop_event.wait(timeout=max(0, sleep_seconds))
        if stop_event.is_set():
            logger.info("Task %s stopping before execution (disabled/gated)", task.name)
            with _lock:
                _task_status.setdefault(task.name, {})
                _task_status[task.name].update({"next_run_at": None, "stopping": False})
            return

        # Prevent overlapping executions
        with _lock:
            if task.name in _running:
                logger.warning(
                    "Task %s still running, skipping this execution",
                    task.name,
                )
                continue
            _running.add(task.name)
            started_at = timezone.now()
            _task_status.setdefault(task.name, {})
            _task_status[task.name].update(
                {
                    "last_started_at": started_at.isoformat(),
                    "last_error": None,
                    "backoff_until_at": None,
                    "backoff_seconds": 0,
                    "suspended": False,
                    "stuck": False,
                }
            )

        try:
            from . import telemetry

            telemetry.update_task_health_started(
                task=task,
                started_at=started_at,
                consecutive_failures_at_start=consecutive_failures,
                thread_name=threading.current_thread().name,
            )
        except Exception:
            pass

        start_time = time.monotonic()
        try:
            close_old_connections()
            logger.info("Task %s starting", task.name)
            task.func()
            duration = time.monotonic() - start_time
            logger.info("Task %s completed in %.2fs", task.name, duration)
            finished_at = timezone.now()
            with _lock:
                status = _task_status.setdefault(task.name, {})
                status["last_finished_at"] = finished_at.isoformat()
                status["last_duration_seconds"] = round(duration, 6)
                status["consecutive_failures"] = 0

            try:
                from . import telemetry

                telemetry.update_task_health_finished_success(
                    task=task,
                    finished_at=finished_at,
                    duration_seconds=duration,
                )
                telemetry.record_task_run_success_if_slow(
                    task=task,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=duration,
                    consecutive_failures_at_start=consecutive_failures,
                    thread_name=threading.current_thread().name,
                )
            except Exception:
                pass
        except Exception as exc:
            duration = time.monotonic() - start_time
            logger.exception(
                "Task %s failed after %.2fs",
                task.name,
                duration,
            )
            finished_at = timezone.now()
            next_consecutive_failures = consecutive_failures + 1
            with _lock:
                status = _task_status.setdefault(task.name, {})
                status["last_finished_at"] = finished_at.isoformat()
                status["last_duration_seconds"] = round(duration, 6)
                status["last_error"] = "exception"
                status["consecutive_failures"] = next_consecutive_failures

            try:
                from . import telemetry

                telemetry.update_task_health_finished_failure(
                    task=task,
                    finished_at=finished_at,
                    duration_seconds=duration,
                    consecutive_failures=next_consecutive_failures,
                    error_message=str(exc),
                )
                telemetry.record_task_run_failure(
                    task=task,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=duration,
                    consecutive_failures_at_start=consecutive_failures,
                    thread_name=threading.current_thread().name,
                    exc=exc,
                )
                telemetry.maybe_emit_failure_event(
                    task_name=task.name,
                    consecutive_failures=next_consecutive_failures,
                    error_message=str(exc),
                )
            except Exception:
                pass
        finally:
            close_old_connections()
            with _lock:
                _running.discard(task.name)


def _run_watchdog() -> None:
    """Monitor task threads and restart any that died."""
    while True:
        time.sleep(_WATCHDOG_INTERVAL)

        with _lock:
            running_task_names = list(_running)
        try:
            from . import telemetry

            telemetry.update_running_task_heartbeats(task_names=running_task_names)
        except Exception:
            pass

        for name, task in get_tasks().items():
            enabled_now, enabled_reason = _task_enabled_now(task)
            with _lock:
                _task_status.setdefault(name, {})
                _task_status[name].update(
                    {
                        "enabled": bool(enabled_now),
                        "enabled_reason": enabled_reason,
                    }
                )

            if not enabled_now:
                with _lock:
                    thread = _threads.get(name)
                    stop = _stop_events.get(name)
                    if thread is not None and thread.is_alive() and stop is not None and not stop.is_set():
                        _task_status.setdefault(name, {})
                        _task_status[name]["stopping"] = True
                        stop.set()
                continue

            now = timezone.now()
            with _lock:
                is_running = name in _running
                last_started_at = _task_status.get(name, {}).get("last_started_at")
                already_stuck = bool(_task_status.get(name, {}).get("stuck"))

            if (
                is_running
                and task.max_runtime_seconds
                and isinstance(last_started_at, str)
                and not already_stuck
            ):
                try:
                    started_at = datetime.fromisoformat(last_started_at)
                    if timezone.is_naive(started_at):
                        started_at = timezone.make_aware(started_at)
                    runtime_seconds = (now - started_at).total_seconds()
                    if runtime_seconds > float(task.max_runtime_seconds):
                        with _lock:
                            status = _task_status.setdefault(name, {})
                            status["stuck"] = True
                            status["stuck_detected_at"] = now.isoformat()
                            status["stuck_for_seconds"] = int(runtime_seconds)
                        logger.error(
                            "Task %s appears stuck (runtime %.0fs > max_runtime_seconds=%s)",
                            name,
                            runtime_seconds,
                            task.max_runtime_seconds,
                        )
                        try:
                            from . import telemetry

                            telemetry.maybe_emit_stuck_event(
                                task_name=name,
                                runtime_seconds=runtime_seconds,
                                max_runtime_seconds=int(task.max_runtime_seconds),
                            )
                        except Exception:
                            pass
                except Exception:
                    pass

            with _lock:
                thread = _threads.get(name)
                if thread is None or not thread.is_alive():
                    if thread is not None:
                        logger.warning("Task %s thread died, restarting...", name)

                    stop_event = threading.Event()
                    new_thread = threading.Thread(
                        target=_run_task_loop,
                        kwargs={"task": task, "stop_event": stop_event},
                        name=f"task-{name}",
                        daemon=True,
                    )
                    new_thread.start()
                    _threads[name] = new_thread
                    _stop_events[name] = stop_event
                    logger.info("Started task thread: %s", name)


def start_scheduler() -> None:
    """Start all registered tasks and the watchdog."""
    global _watchdog_started

    with _lock:
        if _watchdog_started:
            return
        if not _maybe_acquire_leader_lock():
            return
        _watchdog_started = True  # Set early to prevent race conditions

        # Start task threads
        for name, task in get_tasks().items():
            enabled_now, enabled_reason = _task_enabled_now(task)
            _task_status.setdefault(name, {})
            _task_status[name].update(
                {
                    "enabled": bool(enabled_now),
                    "enabled_reason": enabled_reason,
                }
            )

            if not enabled_now:
                continue
            stop_event = threading.Event()
            thread = threading.Thread(
                target=_run_task_loop,
                kwargs={"task": task, "stop_event": stop_event},
                name=f"task-{name}",
                daemon=True,
            )
            thread.start()
            _threads[name] = thread
            _stop_events[name] = stop_event
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
            "leader_lock": {
                "enabled": bool(getattr(settings, "SCHEDULER_LEADER_LOCK_ENABLED", False)),
                "acquired": _leader_lock_acquired,
                "error": _leader_lock_error,
            },
            "tasks": {
                name: {
                    "thread_alive": _threads.get(name) is not None
                    and _threads[name].is_alive(),
                    "currently_running": name in _running,
                    "status": dict(_task_status.get(name) or {}),
                }
                for name in get_tasks()
            },
        }
