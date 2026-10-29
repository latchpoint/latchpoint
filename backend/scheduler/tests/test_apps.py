from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, override_settings

import scheduler
from scheduler import apps as scheduler_apps
from scheduler import get_task, registry
from scheduler.apps import _should_start


class ShouldStartTests(SimpleTestCase):
    @override_settings(SCHEDULER_ENABLED=True, IS_TESTING=False)
    def test_starts_under_daphne_with_flags(self):
        with patch("scheduler.apps.sys.argv", ["/usr/bin/daphne", "-b", "0.0.0.0", "config.asgi:application"]):
            self.assertTrue(_should_start())

    @override_settings(SCHEDULER_ENABLED=True, IS_TESTING=False)
    def test_does_not_start_for_migrate(self):
        with patch("scheduler.apps.sys.argv", ["manage.py", "migrate"]):
            self.assertFalse(_should_start())


@override_settings(SCHEDULER_ENABLED=True, IS_TESTING=False, START_RUNTIMES="auto")
class SchedulerAppReadyTests(SimpleTestCase):
    """`ready()` starts the scheduler only in the server process (#160)."""

    def _run_ready(self, argv: list[str]) -> bool:
        with (
            patch.object(scheduler_apps, "sys", SimpleNamespace(argv=argv)),
            patch("scheduler.runner.start_scheduler") as start_scheduler,
        ):
            apps.get_app_config("scheduler").ready()
        return start_scheduler.called

    def test_skips_startup_in_management_commands(self):
        for command in ("apply_integration_settings", "shell", "createsuperuser"):
            with self.subTest(command=command):
                self.assertFalse(self._run_ready(["manage.py", command]))

    def test_starts_in_the_server(self):
        self.assertTrue(self._run_ready(["daphne", "config.asgi:application"]))

    def test_registers_its_tasks_outside_the_server(self):
        # `list_tasks` and `run_task` are management commands too, so they need the tasks either way. The
        # tasks module is already loaded, so drop it and the registry to see `ready()` load it again. The module
        # is put back by hand rather than with `patch.dict(sys.modules)`, which clears the whole dict to restore it.
        tasks_module = sys.modules.pop("scheduler.tasks")
        try:
            with patch.dict(registry._tasks, clear=True), patch.object(scheduler, "tasks"):
                del scheduler.tasks

                started = self._run_ready(["manage.py", "run_task", "scheduler_cleanup_task_runs"])

                self.assertFalse(started)
                self.assertIsNotNone(get_task("scheduler_cleanup_task_runs"))
        finally:
            sys.modules["scheduler.tasks"] = tasks_module
