"""The Z-Wave JS app's `ready()` connects only in the server process (#160)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.test import TestCase, override_settings

from alarm.gateways.zwavejs import default_zwavejs_gateway
from alarm.signals import settings_profile_changed
from integrations_zwavejs import apps as zwavejs_apps


def _run_ready(argv: list[str]) -> tuple[bool, bool]:
    """Run `ready()` with `argv`. Returns whether it applied the settings and whether it connected its handler."""
    with (
        patch.object(zwavejs_apps, "sys", SimpleNamespace(argv=argv)),
        patch.object(type(default_zwavejs_gateway), "apply_settings") as apply_settings,
    ):
        apps.get_app_config("integrations_zwavejs").ready()
    connected = settings_profile_changed.disconnect(dispatch_uid="zwavejs_settings_changed")
    return apply_settings.called, connected


@override_settings(START_RUNTIMES="auto")
class ZwavejsAppReadyTests(TestCase):
    def test_skips_startup_in_management_commands(self):
        for command in ("apply_integration_settings", "shell", "createsuperuser"):
            with self.subTest(command=command):
                self.assertEqual(_run_ready(["manage.py", command]), (False, False))

    def test_connects_in_the_server(self):
        self.assertEqual(_run_ready(["daphne", "config.asgi:application"]), (True, True))
