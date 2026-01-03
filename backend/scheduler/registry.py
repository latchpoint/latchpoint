"""Task registration and discovery for the scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .schedules import Schedule

_tasks: dict[str, "ScheduledTask"] = {}


@dataclass
class ScheduledTask:
    """A registered scheduled task."""

    name: str
    func: Callable[[], None]
    schedule: Schedule
    enabled: bool = True


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
        _tasks[name] = ScheduledTask(
            name=name,
            func=func,
            schedule=schedule,
            enabled=enabled,
        )
        return func

    return decorator


def get_tasks() -> dict[str, ScheduledTask]:
    """Return a copy of all registered tasks."""
    return _tasks.copy()


def get_task(name: str) -> ScheduledTask | None:
    """Return a specific task by name, or None if not found."""
    return _tasks.get(name)
