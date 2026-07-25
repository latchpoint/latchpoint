from __future__ import annotations

import threading
import time
import traceback
from dataclasses import asdict, is_dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from alarm.models import AlarmEvent, AlarmEventType

from .models import SchedulerTaskHealth, SchedulerTaskRun, SchedulerTaskRunStatus
from .registry import ScheduledTask
from .schedules import Every

_CACHED_INSTANCE_ID: str | None = None

# Single-instance deployments share one bucket; multi-instance operators
# override via SCHEDULER_INSTANCE_ID. See ADR-0093.
_DEFAULT_INSTANCE_ID = "default"

# ADR-0103: fast sub-minute tasks (e.g. process_alarm_timers at 1s) otherwise issue ~3
# `scheduler_taskhealth` UPDATEs per run. Throttle the scheduling/started/finished-success
# writes to at most once per window per task; failures and slow runs stay unconditional.
_HEALTH_THROTTLE_WINDOW_SECONDS = 60.0
_health_throttle_lock = threading.Lock()
_last_health_persist_at: dict[str, float] = {}


def _is_sub_minute_task(task: ScheduledTask) -> bool:
    """Return True for `Every` schedules that fire more often than the throttle window."""
    schedule = task.schedule
    return isinstance(schedule, Every) and int(schedule.seconds) < int(_HEALTH_THROTTLE_WINDOW_SECONDS)


def should_persist_health(*, task: ScheduledTask) -> bool:
    """Decide whether to persist scheduling/started/finished-success health for this run.

    Sub-minute `Every` tasks persist at most once per ~60s window; every other schedule
    (DailyAt, `Every` >= 60s), the first run after process start, and any run past the
    window always persist.

    Call this ONCE per run and reuse the result for both the started (is_running=True) and
    finished-success (is_running=False) writes, so a persisted `started` always has a
    matching finished write and no health row is left stuck at is_running=True. Failure
    writes (`update_task_health_finished_failure`) and slow-run records stay unconditional
    and are intentionally not gated by this decision.
    """
    if not _is_sub_minute_task(task):
        return True
    now = time.monotonic()
    with _health_throttle_lock:
        last = _last_health_persist_at.get(task.name)
        if last is not None and (now - last) < _HEALTH_THROTTLE_WINDOW_SECONDS:
            return False
        _last_health_persist_at[task.name] = now
        return True


def _slow_run_threshold_seconds() -> float:
    """Duration at or above which a run is treated as slow enough to always record."""
    return float(getattr(settings, "SCHEDULER_SLOW_RUN_THRESHOLD_SECONDS", 2.0))


def was_slow_run(*, duration_seconds: float) -> bool:
    """Return True when a run met or exceeded the slow-run threshold."""
    return float(duration_seconds) >= _slow_run_threshold_seconds()


def should_persist_finish(*, task: ScheduledTask, duration_seconds: float) -> bool:
    """Return True when a finished-success write must happen even under the throttle.

    The supervisor persists ``is_running=True`` for a run whose in-flight runtime passed
    ``max_runtime_seconds`` (see ``persist_running_now``), so every such run must also
    write its finish or the health row would stay stuck at ``is_running=True`` until the
    next unthrottled run. Slow-but-not-stuck runs persist too, so the scheduler UI reports
    an accurate ``last_duration_seconds`` for exactly the runs an operator cares about.
    """
    if was_slow_run(duration_seconds=duration_seconds):
        return True
    max_runtime = task.max_runtime_seconds
    return bool(max_runtime) and float(duration_seconds) > float(max_runtime)


def get_instance_id() -> str:
    global _CACHED_INSTANCE_ID
    if _CACHED_INSTANCE_ID:
        return _CACHED_INSTANCE_ID

    override = getattr(settings, "SCHEDULER_INSTANCE_ID", None)
    if isinstance(override, str) and override.strip():
        _CACHED_INSTANCE_ID = override.strip()
        return _CACHED_INSTANCE_ID

    _CACHED_INSTANCE_ID = _DEFAULT_INSTANCE_ID
    return _CACHED_INSTANCE_ID


def serialize_schedule(task: ScheduledTask) -> tuple[str, dict[str, Any]]:
    schedule = task.schedule
    schedule_type = type(schedule).__name__
    if is_dataclass(schedule):
        return schedule_type, asdict(schedule)
    return schedule_type, {}


def _best_effort_update_health(
    *,
    task_name: str,
    instance_id: str,
    defaults: dict[str, Any],
) -> None:
    try:
        updated = SchedulerTaskHealth.objects.filter(
            task_name=task_name,
            instance_id=instance_id,
        ).update(**defaults)
        if updated:
            return
        SchedulerTaskHealth.objects.create(
            task_name=task_name,
            instance_id=instance_id,
            **defaults,
        )
    except IntegrityError:
        try:
            SchedulerTaskHealth.objects.filter(
                task_name=task_name,
                instance_id=instance_id,
            ).update(**defaults)
        except Exception:
            return
    except Exception:
        return


def touch_task_health_registered(*, task: ScheduledTask) -> None:
    instance_id = get_instance_id()
    schedule_type, schedule_payload = serialize_schedule(task)
    _best_effort_update_health(
        task_name=task.name,
        instance_id=instance_id,
        defaults={
            "enabled": bool(task.enabled),
            "schedule_type": schedule_type,
            "schedule_payload": schedule_payload,
            "max_runtime_seconds": task.max_runtime_seconds,
        },
    )


def update_task_health_scheduling(*, task: ScheduledTask, next_run_at) -> None:
    instance_id = get_instance_id()
    schedule_type, schedule_payload = serialize_schedule(task)
    _best_effort_update_health(
        task_name=task.name,
        instance_id=instance_id,
        defaults={
            "enabled": bool(task.enabled),
            "schedule_type": schedule_type,
            "schedule_payload": schedule_payload,
            "max_runtime_seconds": task.max_runtime_seconds,
            "next_run_at": next_run_at,
        },
    )


def update_task_health_started(
    *, task: ScheduledTask, started_at, consecutive_failures_at_start: int, thread_name: str
) -> None:
    instance_id = get_instance_id()
    schedule_type, schedule_payload = serialize_schedule(task)
    _best_effort_update_health(
        task_name=task.name,
        instance_id=instance_id,
        defaults={
            "enabled": bool(task.enabled),
            "schedule_type": schedule_type,
            "schedule_payload": schedule_payload,
            "max_runtime_seconds": task.max_runtime_seconds,
            "is_running": True,
            "last_started_at": started_at,
            "last_heartbeat_at": started_at,
            "consecutive_failures": max(0, int(consecutive_failures_at_start)),
        },
    )


def update_task_health_finished_success(*, task: ScheduledTask, finished_at, duration_seconds: float) -> None:
    instance_id = get_instance_id()
    schedule_type, schedule_payload = serialize_schedule(task)
    _best_effort_update_health(
        task_name=task.name,
        instance_id=instance_id,
        defaults={
            "enabled": bool(task.enabled),
            "schedule_type": schedule_type,
            "schedule_payload": schedule_payload,
            "max_runtime_seconds": task.max_runtime_seconds,
            "is_running": False,
            "last_finished_at": finished_at,
            "last_duration_seconds": float(duration_seconds),
            "consecutive_failures": 0,
            "last_error_message": "",
            "last_heartbeat_at": finished_at,
        },
    )


def update_task_health_finished_failure(
    *,
    task: ScheduledTask,
    finished_at,
    duration_seconds: float,
    consecutive_failures: int,
    error_message: str,
) -> None:
    instance_id = get_instance_id()
    schedule_type, schedule_payload = serialize_schedule(task)
    _best_effort_update_health(
        task_name=task.name,
        instance_id=instance_id,
        defaults={
            "enabled": bool(task.enabled),
            "schedule_type": schedule_type,
            "schedule_payload": schedule_payload,
            "max_runtime_seconds": task.max_runtime_seconds,
            "is_running": False,
            "last_finished_at": finished_at,
            "last_duration_seconds": float(duration_seconds),
            "consecutive_failures": max(0, int(consecutive_failures)),
            "last_error_message": error_message[:4000],
            "last_heartbeat_at": finished_at,
        },
    )


def persist_running_now(*, task: ScheduledTask, started_at) -> None:
    """Persist ``is_running=True`` for a run the supervisor found still in flight.

    Under the ADR-0103 throttle a sub-minute task's ``started`` write is usually skipped,
    which would leave the DB-derived ``running``/``stuck`` status in ``scheduler/views.py``
    blind to a hung run. The supervisor calls this once it detects the run has passed
    ``max_runtime_seconds``, so the health row reflects reality exactly when it matters
    without adding writes to healthy runs. ``should_persist_finish`` guarantees the
    matching ``is_running=False`` write when the run eventually ends.
    """
    instance_id = get_instance_id()
    schedule_type, schedule_payload = serialize_schedule(task)
    _best_effort_update_health(
        task_name=task.name,
        instance_id=instance_id,
        defaults={
            "enabled": bool(task.enabled),
            "schedule_type": schedule_type,
            "schedule_payload": schedule_payload,
            "max_runtime_seconds": task.max_runtime_seconds,
            "is_running": True,
            "last_started_at": started_at,
            "last_heartbeat_at": timezone.now(),
        },
    )


def update_running_task_heartbeats(*, task_names: list[str]) -> None:
    if not task_names:
        return
    instance_id = get_instance_id()
    now = timezone.now()
    try:
        SchedulerTaskHealth.objects.filter(
            instance_id=instance_id,
            task_name__in=task_names,
            is_running=True,
        ).update(last_heartbeat_at=now)
    except Exception:
        return


def record_task_run_failure(
    *,
    task: ScheduledTask,
    started_at,
    finished_at,
    duration_seconds: float,
    consecutive_failures_at_start: int,
    thread_name: str,
    exc: BaseException,
) -> None:
    instance_id = get_instance_id()
    try:
        SchedulerTaskRun.objects.create(
            task_name=task.name,
            instance_id=instance_id,
            started_at=started_at,
            finished_at=finished_at,
            status=SchedulerTaskRunStatus.FAILURE,
            duration_seconds=float(duration_seconds),
            error_message=str(exc)[:4000],
            error_traceback="".join(traceback.format_exception(exc))[:20000],
            consecutive_failures_at_start=max(0, int(consecutive_failures_at_start)),
            thread_name=thread_name[:128],
        )
    except Exception:
        return


def record_task_run_success_if_slow(
    *,
    task: ScheduledTask,
    started_at,
    finished_at,
    duration_seconds: float,
    consecutive_failures_at_start: int,
    thread_name: str,
) -> None:
    if not was_slow_run(duration_seconds=duration_seconds):
        return
    instance_id = get_instance_id()
    try:
        SchedulerTaskRun.objects.create(
            task_name=task.name,
            instance_id=instance_id,
            started_at=started_at,
            finished_at=finished_at,
            status=SchedulerTaskRunStatus.SUCCESS,
            duration_seconds=float(duration_seconds),
            error_message="",
            error_traceback="",
            consecutive_failures_at_start=max(0, int(consecutive_failures_at_start)),
            thread_name=thread_name[:128],
        )
    except Exception:
        return


def maybe_emit_failure_event(*, task_name: str, consecutive_failures: int, error_message: str) -> None:
    threshold = int(getattr(settings, "SCHEDULER_FAILURE_EVENT_THRESHOLD", 3))
    if threshold <= 0:
        return
    if consecutive_failures != threshold:
        return
    try:
        AlarmEvent.objects.create(
            event_type=AlarmEventType.SCHEDULER_TASK_FAILED,
            timestamp=timezone.now(),
            metadata={
                "task_name": task_name,
                "consecutive_failures": consecutive_failures,
                "error_message": error_message[:4000],
                "instance_id": get_instance_id(),
            },
        )
    except Exception:
        return


def maybe_emit_stuck_event(*, task_name: str, runtime_seconds: float, max_runtime_seconds: int) -> None:
    try:
        AlarmEvent.objects.create(
            event_type=AlarmEventType.SCHEDULER_TASK_STUCK,
            timestamp=timezone.now(),
            metadata={
                "task_name": task_name,
                "runtime_seconds": int(runtime_seconds),
                "max_runtime_seconds": int(max_runtime_seconds),
                "instance_id": get_instance_id(),
            },
        )
    except Exception:
        return
