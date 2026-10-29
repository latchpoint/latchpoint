"""`should_start_runtimes()`: only the server process starts the long-running runtimes (#160)."""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from config import settings as settings_module
from config.runtimes import should_start_runtimes

_SERVERS = [
    ["/usr/local/bin/daphne", "-b", "127.0.0.1", "-p", "8000", "config.asgi:application"],
    ["daphne", "config.asgi:application"],
    ["/app/.venv/bin/uvicorn", "config.asgi:application"],
    ["/usr/local/bin/gunicorn", "-k", "uvicorn.workers.UvicornWorker", "config.asgi:application"],
    # `python -m daphne`
    ["/usr/local/lib/python3.12/site-packages/daphne/__main__.py", "config.asgi:application"],
    ["manage.py", "runserver", "0.0.0.0:8000", "--noreload"],
]

_NOT_SERVERS = [
    ["manage.py", "apply_integration_settings"],
    ["manage.py", "migrate", "--noinput"],
    ["manage.py", "shell"],
    ["manage.py", "createsuperuser"],
    ["manage.py", "run_task", "sync_entity_states"],
    ["manage.py", "test"],
    ["/app/.venv/bin/pytest", "backend"],
    # A server's name further along argv isn't the server.
    ["manage.py", "shell", "-c", "import daphne"],
    [],
]


@override_settings(START_RUNTIMES="auto")
class ShouldStartRuntimesTests(SimpleTestCase):
    def setUp(self):
        patcher = patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("RUN_MAIN", None)

    def test_starts_in_server_processes(self):
        for argv in _SERVERS:
            with self.subTest(argv=argv):
                self.assertTrue(should_start_runtimes(argv))

    def test_skips_management_commands_and_test_runners(self):
        for argv in _NOT_SERVERS:
            with self.subTest(argv=argv):
                self.assertFalse(should_start_runtimes(argv))

    def test_runserver_starts_only_in_the_autoreloader_child(self):
        argv = ["manage.py", "runserver"]
        self.assertFalse(should_start_runtimes(argv))

        os.environ["RUN_MAIN"] = "true"
        self.assertTrue(should_start_runtimes(argv))

    def test_true_starts_them_in_any_process(self):
        for value in ("true", "1", "yes", "on", " TRUE "):
            with self.subTest(value=value), override_settings(START_RUNTIMES=value):
                self.assertTrue(should_start_runtimes(["manage.py", "shell"]))

    def test_false_keeps_them_off_in_the_server(self):
        for value in ("false", "0", "no", "off"):
            with self.subTest(value=value), override_settings(START_RUNTIMES=value):
                self.assertFalse(should_start_runtimes(["daphne", "config.asgi:application"]))

    def test_unset_and_auto_detect_from_argv(self):
        for value in ("", "auto", "AUTO", None):
            with self.subTest(value=value), override_settings(START_RUNTIMES=value):
                self.assertTrue(should_start_runtimes(["daphne", "config.asgi:application"]))
                self.assertFalse(should_start_runtimes(["manage.py", "shell"]))

    def test_an_unknown_value_is_logged_and_treated_as_auto(self):
        with override_settings(START_RUNTIMES="sometimes"), self.assertLogs("config.runtimes", "WARNING") as logs:
            self.assertTrue(should_start_runtimes(["daphne", "config.asgi:application"]))
            self.assertFalse(should_start_runtimes(["manage.py", "shell"]))

        self.assertIn("START_RUNTIMES='sometimes'", logs.output[0])


class StartRuntimesEnvUnderTestsTests(SimpleTestCase):
    """
    `START_RUNTIMES` from the env (or `.env`) doesn't reach a test run.

    `=true` would start MQTT, HA and Z-Wave JS against the real config, and `=false` would stop the tests
    that run `ready()` as a server. Reloads `config.settings` with the env var set, like the TZ tests.
    """

    def tearDown(self):
        importlib.reload(settings_module)

    def test_the_env_var_is_ignored_under_tests(self):
        for value in ("true", "false"):
            with self.subTest(value=value), patch.dict(os.environ, {"START_RUNTIMES": value}):
                importlib.reload(settings_module)

                self.assertTrue(settings_module.IS_TESTING)
                self.assertEqual(settings_module.START_RUNTIMES, "auto")
                with override_settings(START_RUNTIMES=settings_module.START_RUNTIMES):
                    self.assertFalse(should_start_runtimes(["manage.py", "test"]))
                    self.assertTrue(should_start_runtimes(["daphne", "config.asgi:application"]))

    def test_the_env_var_is_read_outside_tests(self):
        # What makes the test above pass is the IS_TESTING check, not the env var going unread. `pytest` is put
        # back by hand rather than with `patch.dict(sys.modules)`, which clears the whole dict to restore it.
        pytest_module = sys.modules.pop("pytest", None)
        try:
            with (
                patch.dict(os.environ, {"START_RUNTIMES": "true"}),
                patch.object(sys, "argv", ["daphne", "config.asgi:application"]),
            ):
                importlib.reload(settings_module)
        finally:
            if pytest_module is not None:
                sys.modules["pytest"] = pytest_module

        self.assertFalse(settings_module.IS_TESTING)
        self.assertEqual(settings_module.START_RUNTIMES, "true")
