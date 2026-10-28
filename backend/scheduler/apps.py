"""Django app configuration for the scheduler."""

from __future__ import annotations

import sys

from django.apps import AppConfig
from django.conf import settings

from config.runtimes import should_start_runtimes


def _should_start() -> bool:
    """Determine if the scheduler should start in this process."""
    # Check settings flag
    if not getattr(settings, "SCHEDULER_ENABLED", True):
        return False

    # Don't start during testing
    if getattr(settings, "IS_TESTING", False):
        return False

    # Only the server process runs scheduled tasks, not management commands (#160).
    return should_start_runtimes(sys.argv)


class SchedulerConfig(AppConfig):
    """Django app configuration for the task scheduler."""

    name = "scheduler"
    verbose_name = "Task Scheduler"

    def ready(self) -> None:
        """Start the scheduler when Django is ready."""
        if _should_start():
            # Import tasks to trigger registration
            # Apps should register their tasks in their own ready() method
            # or via autodiscovery of tasks.py modules
            from . import tasks  # noqa: F401
            from .runner import start_scheduler

            start_scheduler()
