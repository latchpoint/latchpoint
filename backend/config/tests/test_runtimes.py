"""`should_start_runtimes()`: only the server process starts the long-running runtimes (#160)."""

from __future__ import annotations

import os
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

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
