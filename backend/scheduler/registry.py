"""Task registration and discovery for the scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from django.conf import settings

from .schedules import Schedule

_tasks: dict[str, "ScheduledTask"] = {}

EnabledWhenPredicate = Callable[[], bool]


@dataclass
class ScheduledTask:
    """A registered scheduled task."""

    name: str
    func: Callable[[], None]
    schedule: Schedule
    enabled: bool = True
    description: str | None = None
    enabled_when: EnabledWhenPredicate | None = None
    max_runtime_seconds: int | None = None
    failure_backoff_base_seconds: int = 0
    failure_backoff_max_seconds: int = 0
    failure_suspend_after: int = 0
    failure_suspend_seconds: int = 0


def register(
    name: str,
    schedule: Schedule,
    enabled: bool = True,
    description: str | None = None,
    enabled_when: EnabledWhenPredicate | None = None,
    failure_backoff_base_seconds: int = 0,
    failure_backoff_max_seconds: int = 0,
    failure_suspend_after: int = 0,
    failure_suspend_seconds: int = 0,
) -> Callable[[Callable[[], None]], Callable[[], None]]:
    """Decorator to register a scheduled task.

    Usage:
        @register("cleanup_old_events", schedule=DailyAt(hour=3, minute=0))
        def cleanup_old_events() -> int:
            ...

    The `failure_*` kwargs declare the default retry policy at the call site.
    SCHEDULER_TASK_OVERRIDES still wins when present, so operators retain the
    final say from Django settings.
    """

    def decorator(func: Callable[[], None]) -> Callable[[], None]:
        overrides = getattr(settings, "SCHEDULER_TASK_OVERRIDES", {}) or {}
        override = overrides.get(name) if isinstance(overrides, dict) else None
        if not isinstance(override, dict):
            override = {}

        resolved_description = description
        if not resolved_description:
            doc = getattr(func, "__doc__", None)
            if isinstance(doc, str):
                for line in doc.strip().splitlines():
                    line = line.strip()
                    if line:
                        resolved_description = line[:500]
                        break

        resolved_enabled = enabled
        if "enabled" in override:
            resolved_enabled = bool(override.get("enabled"))

        max_runtime_seconds = override.get("max_runtime_seconds")
        if max_runtime_seconds is not None:
            max_runtime_seconds = int(max_runtime_seconds)

        def _resolve_failure(key: str, default: int) -> int:
            value = override.get(key)
            return int(value) if value is not None else int(default)

        resolved_failure_backoff_base_seconds = _resolve_failure(
            "failure_backoff_base_seconds", failure_backoff_base_seconds
        )
        resolved_failure_backoff_max_seconds = _resolve_failure(
            "failure_backoff_max_seconds", failure_backoff_max_seconds
        )
        resolved_failure_suspend_after = _resolve_failure("failure_suspend_after", failure_suspend_after)
        resolved_failure_suspend_seconds = _resolve_failure("failure_suspend_seconds", failure_suspend_seconds)

        _tasks[name] = ScheduledTask(
            name=name,
            func=func,
            schedule=schedule,
            enabled=resolved_enabled,
            description=resolved_description,
            enabled_when=enabled_when,
            max_runtime_seconds=max_runtime_seconds,
            failure_backoff_base_seconds=resolved_failure_backoff_base_seconds,
            failure_backoff_max_seconds=resolved_failure_backoff_max_seconds,
            failure_suspend_after=resolved_failure_suspend_after,
            failure_suspend_seconds=resolved_failure_suspend_seconds,
        )
        return func

    return decorator


def get_tasks() -> dict[str, ScheduledTask]:
    """Return a copy of all registered tasks."""
    return _tasks.copy()


def get_task(name: str) -> ScheduledTask | None:
    """Return a specific task by name, or None if not found."""
    return _tasks.get(name)


def evaluate_task_enabled(task: ScheduledTask) -> tuple[bool, str | None]:
    """
    Return (enabled, reason).

    Reasons are best-effort, intended for status/UI:
    - None: enabled
    - "disabled": explicitly disabled (static config / overrides)
    - "gated": disabled by enabled_when predicate
    - "gating_error": enabled_when raised
    """
    if not bool(task.enabled):
        return False, "disabled"

    if task.enabled_when is None:
        return True, None

    try:
        return (True, None) if bool(task.enabled_when()) else (False, "gated")
    except Exception:
        return False, "gating_error"
