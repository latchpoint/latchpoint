from __future__ import annotations

import logging
import sys
import warnings

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class IntegrationsHomeAssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations_home_assistant"

    def ready(self) -> None:
        """Best-effort runtime hooks for HA integrations."""
        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from alarm.env_config import get_mqtt_config
            from alarm.gateways.mqtt import default_mqtt_gateway
            from alarm.signals import alarm_state_change_committed, settings_profile_changed
            from alarm.state_machine.settings import get_active_settings_profile, get_setting_json
            from integrations_home_assistant import mqtt_alarm_entity
            from integrations_home_assistant.connection import set_cached_connection
        except Exception:
            logger.warning("HA integration import failed", exc_info=True)
            return

        # Best-effort: register MQTT subscriptions/hooks if enabled.
        try:
            mqtt_alarm_entity.initialize_home_assistant_mqtt_alarm_entity_integration()
        except Exception:
            logger.warning("MQTT alarm entity initialization failed", exc_info=True)

        def _on_alarm_state_change_committed(sender, *, state_to: str, **_kwargs) -> None:
            """Publish MQTT alarm entity state on committed alarm state changes."""
            try:
                mqtt_alarm_entity.publish_state(state=state_to)
            except Exception:
                logger.warning("MQTT alarm entity state publish failed", exc_info=True)
                return

        alarm_state_change_committed.connect(
            _on_alarm_state_change_committed, dispatch_uid="ha_mqtt_alarm_entity_state"
        )

        def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Refresh HA connection cache and publish discovery/state updates on profile change."""
            # Refresh the HA connection cache so enabled toggle takes effect.
            try:
                set_cached_connection()
            except Exception:
                logger.warning("HA connection cache refresh failed", exc_info=True)

            try:
                from integrations_home_assistant import state_stream

                state_stream.apply_runtime_settings_from_active_profile()
            except Exception:
                logger.warning("HA state stream re-apply failed", exc_info=True)

            try:
                profile = get_active_settings_profile()
                entity_cfg = get_setting_json(profile, "home_assistant_alarm_entity") or {}
                if not isinstance(entity_cfg, dict) or not entity_cfg.get("enabled"):
                    return
                mqtt_cfg = get_mqtt_config()
                default_mqtt_gateway.apply_settings(settings=mqtt_cfg)
                mqtt_alarm_entity.publish_discovery(force=True)
            except Exception:
                logger.warning("MQTT alarm entity profile update failed", exc_info=True)
                return

        settings_profile_changed.connect(
            _on_settings_profile_changed, dispatch_uid="ha_mqtt_alarm_entity_profile_changed"
        )

        # Warm-up HA connection cache from env vars.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Accessing the database during app initialization")
            try:
                set_cached_connection()
            except Exception:
                logger.warning("HA connection warm-up failed", exc_info=True)

            # Best-effort: start/stop realtime HA entity updates based on current settings.
            try:
                from integrations_home_assistant import state_stream

                state_stream.apply_runtime_settings_from_active_profile()
            except Exception:
                logger.warning("HA state stream startup failed", exc_info=True)
