from __future__ import annotations

import logging
import sys

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class IntegrationsHomeAssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations_home_assistant"

    def ready(self) -> None:
        """Register setting maskers and best-effort runtime hooks for HA integrations."""
        # Always register settings maskers (safe in tests/migrations).
        try:
            from alarm.integration_settings_masking import register_setting_masker
            from integrations_home_assistant.config import mask_home_assistant_connection

            register_setting_masker(key="home_assistant_connection", masker=mask_home_assistant_connection)
        except Exception:
            logger.debug("Setting masker registration failed", exc_info=True)

        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from alarm.signals import alarm_state_change_committed
            from alarm.signals import settings_profile_changed
            from integrations_home_assistant import mqtt_alarm_entity
            from integrations_home_assistant.connection import apply_from_active_profile_if_exists, apply_from_profile_id
            from transports_mqtt.config import normalize_mqtt_connection, prepare_runtime_mqtt_connection
            from alarm.gateways.mqtt import default_mqtt_gateway
            from alarm.state_machine.settings import get_active_settings_profile, get_setting_json
        except Exception:
            logger.debug("HA integration import failed", exc_info=True)
            return

        # Best-effort: register MQTT subscriptions/hooks if enabled.
        try:
            mqtt_alarm_entity.initialize_home_assistant_mqtt_alarm_entity_integration()
        except Exception:
            logger.debug("MQTT alarm entity initialization failed", exc_info=True)

        def _on_alarm_state_change_committed(sender, *, state_to: str, **_kwargs) -> None:
            """Publish MQTT alarm entity state on committed alarm state changes."""
            try:
                mqtt_alarm_entity.publish_state(state=state_to)
            except Exception:
                logger.debug("MQTT alarm entity state publish failed", exc_info=True)
                return

        alarm_state_change_committed.connect(_on_alarm_state_change_committed, dispatch_uid="ha_mqtt_alarm_entity_state")

        def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Publish discovery/state updates when relevant profile settings change."""
            try:
                profile = get_active_settings_profile()
                entity_cfg = get_setting_json(profile, "home_assistant_alarm_entity") or {}
                if not isinstance(entity_cfg, dict) or not entity_cfg.get("enabled"):
                    return
                mqtt_cfg = normalize_mqtt_connection(get_setting_json(profile, "mqtt_connection") or {})
                default_mqtt_gateway.apply_settings(settings=prepare_runtime_mqtt_connection(mqtt_cfg))
                mqtt_alarm_entity.publish_discovery(force=True)
            except Exception:
                logger.debug("MQTT alarm entity profile update failed", exc_info=True)
                return

        settings_profile_changed.connect(_on_settings_profile_changed, dispatch_uid="ha_mqtt_alarm_entity_profile_changed")

        def _on_ha_connection_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Apply updated Home Assistant connection settings into the runtime cache."""
            try:
                apply_from_profile_id(profile_id=profile_id)
            except Exception:
                logger.debug("HA connection profile apply failed", exc_info=True)
                return
            try:
                from integrations_home_assistant import state_stream

                state_stream.apply_runtime_settings_from_active_profile()
            except Exception:
                logger.debug("HA state stream apply failed", exc_info=True)
                return

        settings_profile_changed.connect(_on_ha_connection_profile_changed, dispatch_uid="ha_connection_profile_changed")

        # Best-effort warm-up so requests don't need DB lookups for HA connection settings.
        try:
            apply_from_active_profile_if_exists()
        except Exception:
            logger.debug("HA connection warm-up failed", exc_info=True)

        # Best-effort: start/stop realtime HA entity updates based on current settings.
        try:
            from integrations_home_assistant import state_stream

            state_stream.apply_runtime_settings_from_active_profile()
        except Exception:
            logger.debug("HA state stream startup failed", exc_info=True)
