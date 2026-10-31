from __future__ import annotations

import logging
import sys

from django.apps import AppConfig

from config.runtimes import should_start_runtimes


class LocksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "locks"
    verbose_name = "Door Locks"

    def ready(self) -> None:
        # Import tasks to register them with the scheduler
        from . import tasks  # noqa: F401

        # The keypad unlock listener only runs in the process with the runtime
        # lock (ADR-0112), so a use is counted once.
        if not should_start_runtimes(sys.argv):
            return

        try:
            from locks.runtime import initialize

            initialize()
        except Exception:
            logging.getLogger(__name__).exception("Locks: runtime failed to start, keypad uses won't be counted")
