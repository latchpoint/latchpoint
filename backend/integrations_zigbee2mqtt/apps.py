from __future__ import annotations

import logging
import sys
import warnings

from django.apps import AppConfig

from config.runtimes import should_start_runtimes

logger = logging.getLogger(__name__)


class IntegrationsZigbee2mqttConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations_zigbee2mqtt"

    def ready(self) -> None:
        """Best-effort runtime hooks for Zigbee2MQTT integration."""
        # Only the server process starts the runtimes, not management commands or tests (#160).
        if not should_start_runtimes(sys.argv):
            return

        try:
            from alarm.signals import settings_profile_changed
            from integrations_zigbee2mqtt.runtime import (
                apply_runtime_settings_from_active_profile,
                initialize,
            )
        except Exception:
            return

        def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Apply runtime Zigbee2MQTT settings when the profile changes."""
            apply_runtime_settings_from_active_profile()

        settings_profile_changed.connect(
            _on_settings_profile_changed,
            dispatch_uid="zigbee2mqtt_profile_changed",
            weak=False,
        )

        # Subscribe for ingest and hook into MQTT connects at startup. `apply_integration_settings` used to do this
        # on boot, but in its own process, so the server only subscribed on the first status or settings request
        # (#164).
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Accessing the database during app initialization")
            try:
                initialize()
            except Exception:
                logger.warning("Zigbee2MQTT startup failed", exc_info=True)
