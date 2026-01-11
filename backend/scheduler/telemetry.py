from __future__ import annotations

import os
import socket
import traceback
from dataclasses import asdict, is_dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from alarm.models import AlarmEvent, AlarmEventType

from .models import SchedulerTaskHealth, SchedulerTaskRun, SchedulerTaskRunStatus
from .registry import ScheduledTask

_CACHED_INSTANCE_ID: str | None = None


def get_instance_id() -> str:
    global _CACHED_INSTANCE_ID
    if _CACHED_INSTANCE_ID:
        return _CACHED_INSTANCE_ID

    override = getattr(settings, "SCHEDULER_INSTANCE_ID", None)
    if isinstance(override, str) and override.strip():
        _CACHED_INSTANCE_ID = override.strip()
        return _CACHED_INSTANCE_ID

    hostname = socket.gethostname()
    pid = os.getpid()
    _CACHED_INSTANCE_ID = f"{hostname}:{pid}"
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


def update_task_health_started(*, task: ScheduledTask, started_at, consecutive_failures_at_start: int, thread_name: str) -> None:
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
    threshold = float(getattr(settings, "SCHEDULER_SLOW_RUN_THRESHOLD_SECONDS", 2.0))
    if duration_seconds < threshold:
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

