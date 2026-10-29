from __future__ import annotations

import logging
import sys
import warnings

from django.apps import AppConfig

from config.runtimes import should_start_runtimes

logger = logging.getLogger(__name__)


class IntegrationsFrigateConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations_frigate"

    def ready(self) -> None:
        """Register best-effort runtime hooks for Frigate integration settings."""
        # Import tasks to register them with the scheduler. Before the server check, so `list_tasks` and
        # `run_task` still see them.
        from . import tasks  # noqa: F401

        # Only the server process starts the runtimes, not management commands or tests (#160).
        if not should_start_runtimes(sys.argv):
            return

        try:
            from alarm.signals import settings_profile_changed
            from integrations_frigate.runtime import apply_runtime_settings_from_active_profile, initialize
        except Exception:
            return

        def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Apply runtime Frigate settings when the profile changes."""
            apply_runtime_settings_from_active_profile()

        settings_profile_changed.connect(
            _on_settings_profile_changed,
            dispatch_uid="frigate_profile_changed",
            weak=False,
        )

        # Subscribe for events and hook into MQTT connects at startup. `apply_integration_settings` used to do this
        # on boot, but in its own process, so the server only subscribed on the first status or settings request
        # (#164).
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Accessing the database during app initialization")
            try:
                initialize()
            except Exception:
                logger.warning("Frigate startup failed", exc_info=True)
