"""The control panels app's `ready()` starts its runtime only in the server process (#160)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, override_settings

from control_panels import apps as control_panels_apps


def _run_ready(argv: list[str]) -> bool:
    """Run `ready()` with `argv`. Returns whether it initialized the control panels runtime."""
    with (
        patch.object(control_panels_apps, "sys", SimpleNamespace(argv=argv)),
        patch("control_panels.runtime.initialize") as initialize,
    ):
        apps.get_app_config("control_panels").ready()
    return initialize.called


@override_settings(START_RUNTIMES="auto")
class ControlPanelsAppReadyTests(SimpleTestCase):
    def test_skips_startup_in_management_commands(self):
        for command in ("apply_integration_settings", "shell", "createsuperuser"):
            with self.subTest(command=command):
                self.assertFalse(_run_ready(["manage.py", command]))

    def test_starts_the_runtime_in_the_server(self):
        self.assertTrue(_run_ready(["daphne", "config.asgi:application"]))
