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
            from alarm.env_config import get_frigate_config, get_mqtt_config, get_zigbee2mqtt_config
            from alarm.gateways.mqtt import default_mqtt_gateway
        except Exception:
            return

        def _apply_from_env() -> None:
            """Apply MQTT settings from env vars to the runtime gateway (best-effort)."""
            try:
                cfg = get_mqtt_config()
                default_mqtt_gateway.apply_settings(settings=cfg)
            except Exception:
                return

        # Startup validation: warn if MQTT is disabled but dependents are enabled.
        mqtt_cfg = get_mqtt_config()
        if not mqtt_cfg["enabled"]:
            z2m = get_zigbee2mqtt_config()
            frigate = get_frigate_config()
            if z2m["enabled"]:
                logger.warning("ZIGBEE2MQTT_ENABLED=true but MQTT_ENABLED=false; Zigbee2MQTT will not function")
            if frigate["enabled"]:
                logger.warning("FRIGATE_ENABLED=true but MQTT_ENABLED=false; Frigate will not function")

        # Apply settings once at process startup.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Accessing the database during app initialization")
            _apply_from_env()
