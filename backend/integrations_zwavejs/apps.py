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
            from alarm.env_config import get_zwavejs_config
            from alarm.gateways.zwavejs import default_zwavejs_gateway
        except Exception:
            return

        def _apply_from_env() -> None:
            """Apply Z-Wave JS settings from env vars to the runtime gateway (best-effort)."""
            try:
                cfg = get_zwavejs_config()
                default_zwavejs_gateway.apply_settings(settings_obj=cfg)
            except Exception:
                return

        # Apply settings once at process startup.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Accessing the database during app initialization")
            _apply_from_env()
