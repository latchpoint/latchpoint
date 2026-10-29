"""The Zigbee2MQTT app's `ready()` starts its runtime only in the server process (#160, #164)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, override_settings

from alarm.signals import settings_profile_changed
from integrations_zigbee2mqtt import apps as z2m_apps


def _run_ready(argv: list[str]) -> bool:
    """Run `ready()` with `argv`. Returns whether it connected its profile change handler."""
    return _run_ready_with_initialize(argv)[0]


def _run_ready_with_initialize(argv: list[str]) -> tuple[bool, bool]:
    """Run `ready()` with `argv`. Returns whether it connected its profile change handler and initialized."""
    with (
        patch.object(z2m_apps, "sys", SimpleNamespace(argv=argv)),
        patch("integrations_zigbee2mqtt.runtime.initialize") as initialize,
    ):
        apps.get_app_config("integrations_zigbee2mqtt").ready()
    connected = settings_profile_changed.disconnect(dispatch_uid="zigbee2mqtt_profile_changed")
    return connected, initialize.called


@override_settings(START_RUNTIMES="auto")
class Zigbee2mqttAppReadyTests(SimpleTestCase):
    def test_skips_startup_in_management_commands(self):
        for command in ("apply_integration_settings", "shell", "createsuperuser"):
            with self.subTest(command=command):
                self.assertFalse(_run_ready(["manage.py", command]))

    def test_hooks_profile_changes_in_the_server(self):
        self.assertTrue(_run_ready(["daphne", "config.asgi:application"]))

    def test_subscribes_only_at_server_startup(self):
        # `apply_integration_settings` used to do this on boot, but in its own process (#164).
        self.assertEqual(_run_ready_with_initialize(["manage.py", "apply_integration_settings"]), (False, False))
        self.assertEqual(_run_ready_with_initialize(["daphne", "config.asgi:application"]), (True, True))
