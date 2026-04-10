from __future__ import annotations

import logging
import sys
import warnings

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class TransportsMqttConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "transports_mqtt"

    def ready(self) -> None:
        """Best-effort runtime hooks for MQTT transport."""
        # Avoid side effects during migrations/collectstatic/tests.
        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from alarm.env_config import get_mqtt_config
            from alarm.gateways.mqtt import default_mqtt_gateway
            from alarm.integration_helpers import get_integration_enabled
            from alarm.signals import settings_profile_changed
        except Exception:
            return

        def _apply_mqtt_settings() -> None:
            """Apply MQTT settings from env vars + enabled from DB to the runtime gateway."""
            try:
                cfg = get_mqtt_config()
                cfg["enabled"] = get_integration_enabled("mqtt")
                default_mqtt_gateway.apply_settings(settings=cfg)
            except Exception:
                return

        def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Re-apply MQTT settings when profile changes (e.g. enabled toggled)."""
            _apply_mqtt_settings()

        settings_profile_changed.connect(
            _on_settings_profile_changed,
            dispatch_uid="mqtt_transport_profile_changed",
        )

        # Apply settings once at process startup.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Accessing the database during app initialization")
            _apply_mqtt_settings()
