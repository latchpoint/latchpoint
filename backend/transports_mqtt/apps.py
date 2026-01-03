from __future__ import annotations

import sys

from django.apps import AppConfig


class TransportsMqttConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "transports_mqtt"

    def ready(self) -> None:
        """Register setting maskers and best-effort runtime hooks for MQTT transport."""
        # Always register settings maskers (safe in tests/migrations).
        try:
            from alarm.integration_settings_masking import register_setting_masker
            from transports_mqtt.config import mask_mqtt_connection

            register_setting_masker(key="mqtt_connection", masker=mask_mqtt_connection)
        except Exception:
            pass

        # Avoid side effects during migrations/collectstatic/tests.
        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from alarm.gateways.mqtt import default_mqtt_gateway
            from alarm.signals import settings_profile_changed
            from alarm.state_machine.settings import get_active_settings_profile, get_setting_json
            from transports_mqtt.config import normalize_mqtt_connection, prepare_runtime_mqtt_connection
        except Exception:
            return

        def _apply_from_active_profile() -> None:
            """Apply MQTT settings from the active profile to the runtime gateway (best-effort)."""
            try:
                profile = get_active_settings_profile()
                settings_obj = normalize_mqtt_connection(get_setting_json(profile, "mqtt_connection") or {})
                default_mqtt_gateway.apply_settings(settings=prepare_runtime_mqtt_connection(settings_obj))
            except Exception:
                return

        def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Refresh runtime MQTT settings when the profile changes."""
            _apply_from_active_profile()

        settings_profile_changed.connect(_on_settings_profile_changed, dispatch_uid="mqtt_transport_profile_changed")

        # Apply settings once at process startup so the runtime connection manager is configured
        # even if no HTTP status endpoint is hit (e.g. clients rely on websocket snapshots).
        _apply_from_active_profile()
