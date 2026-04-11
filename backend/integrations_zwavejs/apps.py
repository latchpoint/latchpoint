from __future__ import annotations

import logging
import sys
import warnings

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class IntegrationsZwavejsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations_zwavejs"

    def ready(self) -> None:
        """Best-effort runtime hooks for Z-Wave JS integration."""
        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from alarm.gateways.zwavejs import default_zwavejs_gateway
            from alarm.signals import settings_profile_changed
        except Exception:
            return

        def _apply_zwavejs_settings() -> None:
            """Apply Z-Wave JS settings from DB to the runtime gateway."""
            try:
                from integrations_zwavejs.views import get_zwavejs_settings

                cfg = get_zwavejs_settings()
                default_zwavejs_gateway.apply_settings(settings_obj=cfg)
            except Exception:
                return

        def _on_settings_changed(sender, **_kwargs) -> None:
            _apply_zwavejs_settings()

        settings_profile_changed.connect(
            _on_settings_changed,
            dispatch_uid="zwavejs_settings_changed",
            weak=False,
        )

        # Apply settings once at process startup.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Accessing the database during app initialization")
            _apply_zwavejs_settings()
