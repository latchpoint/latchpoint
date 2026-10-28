from __future__ import annotations

import sys

from django.apps import AppConfig

from config.runtimes import should_start_runtimes


class ControlPanelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "control_panels"

    def ready(self) -> None:
        """Initialize control panel runtime listeners (only in the server process)."""
        # Import tasks to register them with the scheduler
        from . import tasks  # noqa: F401

        # Runtime wiring (signals / integration hooks) lives in this app to keep alarm core clean.
        # Only the server process starts the runtimes, not management commands or tests (#160).
        if not should_start_runtimes(sys.argv):
            return

        try:
            from control_panels.runtime import initialize

            initialize()
        except Exception:
            return
