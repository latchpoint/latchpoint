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
        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from alarm.gateways.mqtt import default_mqtt_gateway
            from alarm.signals import settings_profile_changed
        except Exception:
            return

        def _apply_mqtt_settings() -> None:
            """Apply MQTT settings from DB to the runtime gateway."""
            try:
                from transports_mqtt.views import get_mqtt_settings

                cfg = get_mqtt_settings()
                default_mqtt_gateway.apply_settings(settings=cfg)
            except Exception:
                return

        # Startup validation: warn if MQTT disabled but dependents enabled.
        try:
            from alarm.integration_helpers import mqtt_enabled
            from alarm.state_machine.settings import get_active_settings_profile, get_setting_json

            if not mqtt_enabled():
                profile = get_active_settings_profile()
                z2m_raw = get_setting_json(profile, "zigbee2mqtt") or {}
                frigate_raw = get_setting_json(profile, "frigate") or {}
                if isinstance(z2m_raw, dict) and z2m_raw.get("enabled"):
                    logger.warning("Zigbee2MQTT enabled but MQTT is disabled; Zigbee2MQTT will not function")
                if isinstance(frigate_raw, dict) and frigate_raw.get("enabled"):
                    logger.warning("Frigate enabled but MQTT is disabled; Frigate will not function")
        except Exception:
            pass

        def _on_settings_changed(sender, **_kwargs) -> None:
            _apply_mqtt_settings()

        settings_profile_changed.connect(
            _on_settings_changed,
            dispatch_uid="mqtt_settings_changed",
            weak=False,
        )

        # Apply settings once at process startup.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Accessing the database during app initialization")
            _apply_mqtt_settings()
