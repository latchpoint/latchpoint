from __future__ import annotations

import sys

from django.apps import AppConfig


class IntegrationsFrigateConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations_frigate"

    def ready(self) -> None:
        """Register best-effort runtime hooks for Frigate integration settings."""
        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from alarm.signals import settings_profile_changed
            from integrations_frigate.runtime import apply_runtime_settings_from_active_profile
        except Exception:
            return

        def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Apply runtime Frigate settings when the profile changes."""
            apply_runtime_settings_from_active_profile()

        settings_profile_changed.connect(
            _on_settings_profile_changed,
            dispatch_uid="frigate_profile_changed",
        )

        # Import tasks to register them with the scheduler
        from . import tasks  # noqa: F401
