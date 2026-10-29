"""`apply_integration_settings` only reads the settings on boot, the server applies them (#164)."""

from __future__ import annotations

import socket
import time
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from transports_mqtt.manager import mqtt_connection_manager

from alarm.gateways.mqtt import default_mqtt_gateway
from alarm.tests.settings_test_utils import EncryptionTestMixin, set_profile_settings
from alarm.use_cases.settings_profile import ensure_active_settings_profile


def _mqtt_client_connected(listener: socket.socket) -> bool:
    """Return True if an MQTT client connects to `listener` before it times out.

    Checks for the CONNECT packet (first byte 0x10), so some other local process poking the port doesn't count.
    """
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            conn, _addr = listener.accept()
        except TimeoutError:
            return False
        with conn:
            conn.settimeout(1.0)
            try:
                if conn.recv(1) == b"\x10":
                    return True
            except OSError:
                continue
    return False


def _enable_everything(profile, *, mqtt_port: int = 1883) -> None:
    set_profile_settings(
        profile,
        mqtt={"enabled": True, "host": "127.0.0.1", "port": mqtt_port},
        zwavejs={"enabled": True, "ws_url": "ws://127.0.0.1:3000"},
        home_assistant_alarm_entity={"enabled": True},
        zigbee2mqtt={"enabled": True},
        frigate={"enabled": True},
    )


class ApplyIntegrationSettingsCommandTests(EncryptionTestMixin, TestCase):
    def setUp(self):
        self.profile = ensure_active_settings_profile()

    def _call(self) -> str:
        out = StringIO()
        call_command("apply_integration_settings", stdout=out)
        return out.getvalue()

    def test_connects_to_nothing(self):
        # A real listener standing in for the broker, so a connect from anywhere in the command shows up.
        listener = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(listener.close)
        listener.settimeout(1.0)
        _enable_everything(self.profile, mqtt_port=listener.getsockname()[1])
        # Before #164 the command left a connected client behind in this process.
        default_mqtt_gateway.apply_settings(settings={"enabled": False})
        self.addCleanup(default_mqtt_gateway.apply_settings, settings={"enabled": False})

        self._call()

        self.assertIsNone(mqtt_connection_manager._client)
        self.assertFalse(_mqtt_client_connected(listener))

    def test_applies_no_runtime(self):
        _enable_everything(self.profile)

        with (
            patch.object(type(default_mqtt_gateway), "apply_settings") as mqtt_apply,
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.apply_settings") as zwavejs_apply,
            patch(
                "integrations_home_assistant.mqtt_alarm_entity.initialize_home_assistant_mqtt_alarm_entity_integration"
            ) as ha_init,
            patch("integrations_home_assistant.mqtt_alarm_entity.publish_discovery") as ha_discovery,
            patch("integrations_zigbee2mqtt.runtime.apply_runtime_settings_from_active_profile") as z2m_apply,
            patch("integrations_frigate.runtime.apply_runtime_settings_from_active_profile") as frigate_apply,
        ):
            self._call()

        for mock in (mqtt_apply, zwavejs_apply, ha_init, ha_discovery, z2m_apply, frigate_apply):
            with self.subTest(mock=mock):
                mock.assert_not_called()

    def test_says_the_server_publishes_discovery(self):
        # It used to print "Published ... discovery." even right after `publish_discovery()` logged that MQTT
        # wasn't connected and skipped it.
        _enable_everything(self.profile)

        output = self._call()

        self.assertNotIn("Published", output)
        self.assertIn(
            "Home Assistant MQTT alarm entity is enabled, the server publishes discovery once MQTT connects.", output
        )
        self.assertIn("MQTT is enabled, the server connects when it starts.", output)
        self.assertIn("Z-Wave JS is enabled, the server connects when it starts.", output)
        self.assertIn("Zigbee2MQTT is enabled, the server subscribes once MQTT connects.", output)
        self.assertIn("Frigate is enabled, the server subscribes once MQTT connects.", output)

    def test_reports_disabled_integrations(self):
        set_profile_settings(
            self.profile,
            mqtt={"enabled": False},
            zwavejs={"enabled": False},
            home_assistant_alarm_entity={"enabled": False},
            zigbee2mqtt={"enabled": False},
            frigate={"enabled": False},
        )

        output = self._call()

        for name in ("MQTT", "Z-Wave JS", "Home Assistant MQTT alarm entity", "Zigbee2MQTT", "Frigate"):
            with self.subTest(name=name):
                self.assertIn(f"{name} is disabled.", output)
