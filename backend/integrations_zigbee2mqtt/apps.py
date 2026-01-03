from __future__ import annotations

import sys

from django.apps import AppConfig


class IntegrationsZigbee2mqttConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations_zigbee2mqtt"

    def ready(self) -> None:
        """Register setting maskers and best-effort runtime hooks for Zigbee2MQTT integration."""
        # Always register settings maskers (safe in tests/migrations).
        try:
            from alarm.integration_settings_masking import register_setting_masker
            from integrations_zigbee2mqtt.config import mask_zigbee2mqtt_settings

            register_setting_masker(key="zigbee2mqtt", masker=mask_zigbee2mqtt_settings)
        except Exception:
            pass

        # Avoid side effects during migrations/collectstatic/tests.
        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from alarm.signals import settings_profile_changed
            from integrations_zigbee2mqtt.runtime import (
                apply_runtime_settings_from_active_profile,
            )
        except Exception:
            return

        def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Apply runtime Zigbee2MQTT settings when the profile changes."""
            apply_runtime_settings_from_active_profile()

        settings_profile_changed.connect(
            _on_settings_profile_changed,
            dispatch_uid="zigbee2mqtt_profile_changed",
        )
