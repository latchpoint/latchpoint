"""In-process task scheduler with watchdog.

This module provides a lightweight scheduler for running periodic tasks
within the Django process, without requiring external infrastructure.

Usage:
    from core.scheduler import register, DailyAt, Every

    @register("my_task", schedule=DailyAt(hour=3, minute=0))
    def my_task() -> None:
        ...

    @register("frequent_task", schedule=Every(seconds=300))
    def frequent_task() -> None:
        ...
"""

from .registry import get_task, get_tasks, register, ScheduledTask
from .runner import get_scheduler_status, start_scheduler
from .schedules import DailyAt, Every, Schedule

__all__ = [
    # Schedule types
    "Schedule",
    "DailyAt",
    "Every",
    # Registration
    "register",
    "ScheduledTask",
    "get_tasks",
    "get_task",
    # Runner
    "start_scheduler",
    "get_scheduler_status",
]
