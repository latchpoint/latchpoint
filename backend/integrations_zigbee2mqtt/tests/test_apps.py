"""The Zigbee2MQTT app's `ready()` hooks into profile changes only in the server process (#160)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, override_settings

from alarm.signals import settings_profile_changed
from integrations_zigbee2mqtt import apps as z2m_apps


def _run_ready(argv: list[str]) -> bool:
    """Run `ready()` with `argv`. Returns whether it connected its profile change handler."""
    with patch.object(z2m_apps, "sys", SimpleNamespace(argv=argv)):
        apps.get_app_config("integrations_zigbee2mqtt").ready()
    return settings_profile_changed.disconnect(dispatch_uid="zigbee2mqtt_profile_changed")


@override_settings(START_RUNTIMES="auto")
class Zigbee2mqttAppReadyTests(SimpleTestCase):
    def test_skips_startup_in_management_commands(self):
        for command in ("apply_integration_settings", "shell", "createsuperuser"):
            with self.subTest(command=command):
                self.assertFalse(_run_ready(["manage.py", command]))

    def test_hooks_profile_changes_in_the_server(self):
        self.assertTrue(_run_ready(["daphne", "config.asgi:application"]))
