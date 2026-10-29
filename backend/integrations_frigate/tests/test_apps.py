"""The Frigate app's `ready()` hooks into profile changes only in the server process (#160)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, override_settings

import integrations_frigate
from alarm.signals import settings_profile_changed
from integrations_frigate import apps as frigate_apps
from scheduler import get_task, registry


def _run_ready(argv: list[str]) -> bool:
    """Run `ready()` with `argv`. Returns whether it connected its profile change handler."""
    with patch.object(frigate_apps, "sys", SimpleNamespace(argv=argv)):
        apps.get_app_config("integrations_frigate").ready()
    return settings_profile_changed.disconnect(dispatch_uid="frigate_profile_changed")


@override_settings(START_RUNTIMES="auto")
class FrigateAppReadyTests(SimpleTestCase):
    def test_skips_startup_in_management_commands(self):
        for command in ("apply_integration_settings", "shell", "createsuperuser"):
            with self.subTest(command=command):
                self.assertFalse(_run_ready(["manage.py", command]))

    def test_hooks_profile_changes_in_the_server(self):
        self.assertTrue(_run_ready(["daphne", "config.asgi:application"]))

    def test_registers_its_tasks_outside_the_server(self):
        # `list_tasks` and `run_task` are management commands too, so they need the tasks either way. The
        # tasks module is already loaded, so drop it and the registry to see `ready()` load it again. The module
        # is put back by hand rather than with `patch.dict(sys.modules)`, which clears the whole dict to restore it.
        tasks_module = sys.modules.pop("integrations_frigate.tasks")
        try:
            with patch.dict(registry._tasks, clear=True), patch.object(integrations_frigate, "tasks"):
                del integrations_frigate.tasks

                _run_ready(["manage.py", "run_task", "cleanup_frigate_detections"])

                self.assertIsNotNone(get_task("cleanup_frigate_detections"))
        finally:
            sys.modules["integrations_frigate.tasks"] = tasks_module
