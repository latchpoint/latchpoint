from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase

from alarm.tests.settings_test_utils import EncryptionTestMixin, set_profile_settings
from alarm.use_cases.settings_profile import ensure_active_settings_profile


class ApplyIntegrationSettingsCommandTests(EncryptionTestMixin, TestCase):
    def test_applies_mqtt_and_zwavejs_and_publishes_ha_discovery_when_enabled(self):
        profile = ensure_active_settings_profile()
        set_profile_settings(
            profile,
            mqtt={"enabled": True, "host": "mqtt.local", "port": 1883},
            zwavejs={"enabled": True, "ws_url": "ws://zwavejs.local:3000"},
            home_assistant_alarm_entity={"enabled": True},
        )

        mqtt_gateway = SimpleNamespace(apply_settings=Mock())
        zwave_gateway = SimpleNamespace(apply_settings=Mock())

        with (
            patch("alarm.management.commands.apply_integration_settings.default_mqtt_gateway", mqtt_gateway),
            patch("alarm.management.commands.apply_integration_settings.default_zwavejs_gateway", zwave_gateway),
            patch(
                "integrations_home_assistant.mqtt_alarm_entity.initialize_home_assistant_mqtt_alarm_entity_integration"
            ) as init_ha,
            patch("integrations_home_assistant.mqtt_alarm_entity.publish_discovery") as pub_discovery,
        ):
            call_command("apply_integration_settings")

        mqtt_gateway.apply_settings.assert_called()
        zwave_gateway.apply_settings.assert_called()
        init_ha.assert_called()
        pub_discovery.assert_called()
