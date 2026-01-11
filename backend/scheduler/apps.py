"""Django app configuration for the scheduler."""

from __future__ import annotations

import os
import sys

from django.apps import AppConfig
from django.conf import settings


def _should_start() -> bool:
    """Determine if the scheduler should start in this process."""
    # Check settings flag
    if not getattr(settings, "SCHEDULER_ENABLED", True):
        return False

    # Don't start during testing
    if getattr(settings, "IS_TESTING", False):
        return False

    # If we're running under a server binary (daphne/uvicorn/gunicorn), start the scheduler.
    #
    # Note: these servers commonly pass flags as argv[1] (e.g. `daphne -b ...`), so we must
    # not interpret argv[1] as a Django management command.
    argv0 = os.path.basename(sys.argv[0] or "")
    if any(server in argv0 for server in ("gunicorn", "uvicorn", "daphne")):
        return True

    # For Django management commands, don't start during migrations/shell/etc.
    # Only allow development servers that should run scheduled tasks in-process.
    if len(sys.argv) > 1:
        command = sys.argv[1]
        allowed_commands = {"runserver", "run"}
        if command not in allowed_commands:
            return False

    return "runserver" in sys.argv or "run" in sys.argv


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
