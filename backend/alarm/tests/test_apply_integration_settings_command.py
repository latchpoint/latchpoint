from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase

from alarm.models import AlarmSettingsEntry
from alarm.use_cases.settings_profile import ensure_active_settings_profile


class ApplyIntegrationSettingsCommandTests(TestCase):
    @patch.dict(os.environ, {
        "MQTT_ENABLED": "true", "MQTT_HOST": "mqtt.local", "MQTT_PORT": "1883",
        "ZWAVEJS_ENABLED": "true", "ZWAVEJS_WS_URL": "ws://zwavejs.local:3000",
    })
    def test_applies_mqtt_and_zwavejs_and_publishes_ha_discovery_when_enabled(self):
        profile = ensure_active_settings_profile()
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="home_assistant_alarm_entity",
            defaults={"value_type": "json", "value": {"enabled": True}},
        )

        mqtt_gateway = SimpleNamespace(apply_settings=Mock())
        zwave_gateway = SimpleNamespace(apply_settings=Mock())

        with (
            patch("alarm.management.commands.apply_integration_settings.default_mqtt_gateway", mqtt_gateway),
            patch("alarm.management.commands.apply_integration_settings.default_zwavejs_gateway", zwave_gateway),
            patch("integrations_home_assistant.mqtt_alarm_entity.initialize_home_assistant_mqtt_alarm_entity_integration") as init_ha,
            patch("integrations_home_assistant.mqtt_alarm_entity.publish_discovery") as pub_discovery,
        ):
            call_command("apply_integration_settings")

        mqtt_gateway.apply_settings.assert_called()
        zwave_gateway.apply_settings.assert_called()
        init_ha.assert_called()
        pub_discovery.assert_called()
