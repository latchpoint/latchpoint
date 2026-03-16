from __future__ import annotations

from django.core.management.base import BaseCommand

from alarm.env_config import get_mqtt_config, get_zwavejs_config
from alarm.gateways.mqtt import default_mqtt_gateway
from alarm.gateways.zwavejs import default_zwavejs_gateway
from alarm.state_machine.settings import get_active_settings_profile, get_setting_json


class Command(BaseCommand):
    help = "Apply integration settings to runtimes (MQTT, Z-Wave JS, HA MQTT alarm entity)."

    def handle(self, *args, **options):
        """Apply integration settings to runtime gateways (best-effort)."""
        mqtt_config = get_mqtt_config()
        default_mqtt_gateway.apply_settings(settings=mqtt_config)
        self.stdout.write("Applied MQTT connection settings from env.")

        zwavejs_config = get_zwavejs_config()
        default_zwavejs_gateway.apply_settings(settings_obj=zwavejs_config)
        self.stdout.write("Applied Z-Wave JS connection settings from env.")

        # Best-effort: if HA MQTT alarm entity is enabled, republish discovery/state.
        profile = get_active_settings_profile()
        ha_entity_raw = get_setting_json(profile, "home_assistant_alarm_entity") or {}
        if isinstance(ha_entity_raw, dict) and ha_entity_raw.get("enabled"):
            try:
                from integrations_home_assistant import mqtt_alarm_entity

                mqtt_alarm_entity.initialize_home_assistant_mqtt_alarm_entity_integration()
                mqtt_alarm_entity.publish_discovery(force=True)
                self.stdout.write("Published Home Assistant MQTT alarm entity discovery.")
            except Exception as exc:
                self.stderr.write(f"Failed to publish HA MQTT alarm entity discovery: {exc}")

        # Best-effort: if Zigbee2MQTT is enabled, set up subscriptions and allow sync/ingest.
        z2m_raw = get_setting_json(profile, "zigbee2mqtt") or {}
        if isinstance(z2m_raw, dict) and z2m_raw.get("enabled"):
            try:
                from integrations_zigbee2mqtt.runtime import apply_runtime_settings_from_active_profile

                apply_runtime_settings_from_active_profile()
                self.stdout.write("Applied Zigbee2MQTT integration runtime settings.")
            except Exception as exc:
                self.stderr.write(f"Failed to apply Zigbee2MQTT integration settings: {exc}")

        # Best-effort: if Frigate is enabled, set up MQTT subscriptions for event ingest.
        frigate_raw = get_setting_json(profile, "frigate") or {}
        if isinstance(frigate_raw, dict) and frigate_raw.get("enabled"):
            try:
                from integrations_frigate.runtime import apply_runtime_settings_from_active_profile

                apply_runtime_settings_from_active_profile()
                self.stdout.write("Applied Frigate integration runtime settings.")
            except Exception as exc:
                self.stderr.write(f"Failed to apply Frigate integration settings: {exc}")
