"""Task registration and discovery for the scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from django.conf import settings

from .schedules import Schedule

_tasks: dict[str, "ScheduledTask"] = {}


@dataclass
class ScheduledTask:
    """A registered scheduled task."""

    name: str
    func: Callable[[], None]
    schedule: Schedule
    enabled: bool = True
    max_runtime_seconds: int | None = None
    failure_backoff_base_seconds: int = 0
    failure_backoff_max_seconds: int = 0
    failure_suspend_after: int = 0
    failure_suspend_seconds: int = 0


def register(
    name: str,
    schedule: Schedule,
    enabled: bool = True,
) -> Callable[[Callable[[], None]], Callable[[], None]]:
    """Decorator to register a scheduled task.

    Usage:
        @register("cleanup_old_events", schedule=DailyAt(hour=3, minute=0))
        def cleanup_old_events() -> int:
            ...
    """

    def decorator(func: Callable[[], None]) -> Callable[[], None]:
        overrides = getattr(settings, "SCHEDULER_TASK_OVERRIDES", {}) or {}
        override = overrides.get(name) if isinstance(overrides, dict) else None
        if not isinstance(override, dict):
            override = {}

        resolved_enabled = enabled
        if "enabled" in override:
            resolved_enabled = bool(override.get("enabled"))

        max_runtime_seconds = override.get("max_runtime_seconds")
        if max_runtime_seconds is not None:
            max_runtime_seconds = int(max_runtime_seconds)

        failure_backoff_base_seconds = int(override.get("failure_backoff_base_seconds") or 0)
        failure_backoff_max_seconds = int(override.get("failure_backoff_max_seconds") or 0)
        failure_suspend_after = int(override.get("failure_suspend_after") or 0)
        failure_suspend_seconds = int(override.get("failure_suspend_seconds") or 0)

        _tasks[name] = ScheduledTask(
            name=name,
            func=func,
            schedule=schedule,
            enabled=resolved_enabled,
            max_runtime_seconds=max_runtime_seconds,
            failure_backoff_base_seconds=failure_backoff_base_seconds,
            failure_backoff_max_seconds=failure_backoff_max_seconds,
            failure_suspend_after=failure_suspend_after,
            failure_suspend_seconds=failure_suspend_seconds,
        )
        return func

    return decorator


def get_tasks() -> dict[str, ScheduledTask]:
    """Return a copy of all registered tasks."""
    return _tasks.copy()


def get_task(name: str) -> ScheduledTask | None:
    """Return a specific task by name, or None if not found."""
    return _tasks.get(name)
