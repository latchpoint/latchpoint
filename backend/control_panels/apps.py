from __future__ import annotations

import sys

from django.apps import AppConfig


class ControlPanelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "control_panels"

    def ready(self) -> None:
        """Initialize control panel runtime listeners (skips migrations/tests/collectstatic)."""
        # Runtime wiring (signals / integration hooks) lives in this app to keep alarm core clean.
        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from control_panels.runtime import initialize

            initialize()
        except Exception:
            return
