"""The log broadcast thread runs only in the server process (#164)."""

from __future__ import annotations

import logging
import queue
import threading
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, override_settings

from alarm import apps as alarm_apps
from alarm import log_handler


def _run_ready(argv: list[str]) -> bool:
    """Run the alarm app's `ready()` with `argv`. Returns whether it started the broadcast thread."""
    with (
        patch.object(alarm_apps, "sys", SimpleNamespace(argv=argv)),
        patch.object(log_handler, "start_broadcast_worker") as start,
    ):
        apps.get_app_config("alarm").ready()
    return start.called


def _warning(msg: str = "something broke") -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logger", level=logging.WARNING, pathname="test.py", lineno=1, msg=msg, args=(), exc_info=None
    )


class _RecordingChannelLayer:
    """Stands in for the in-memory channel layer and records what the worker sends."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.event = threading.Event()

    async def group_send(self, group: str, message: dict) -> None:
        self.sent.append((group, message))
        self.event.set()


@override_settings(START_RUNTIMES="auto")
class LogBroadcastStartupTests(SimpleTestCase):
    def setUp(self):
        log_handler.configure(buffer_size=500, capture_level=logging.DEBUG, broadcast_level=logging.WARNING)

    def test_importing_the_module_starts_no_thread(self):
        # This test run is a non-server process, and it went through `ready()` like any other.
        self.assertIsNone(log_handler._broadcast_thread)

    def test_management_commands_dont_start_it(self):
        for argv in (
            ["manage.py", "apply_integration_settings"],
            ["manage.py", "migrate", "--noinput"],
            ["manage.py", "shell"],
            ["manage.py", "run_task", "sync_entity_states"],
            ["manage.py", "test"],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(_run_ready(argv))

    def test_the_server_starts_it(self):
        for argv in (["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"], ["uvicorn", "x:app"]):
            with self.subTest(argv=argv):
                self.assertTrue(_run_ready(argv))

    def test_nothing_is_queued_without_the_worker(self):
        # Nothing would drain it, so the queue would only grow for as long as the process runs.
        entries: queue.SimpleQueue = queue.SimpleQueue()
        with patch.object(log_handler, "_broadcast_queue", entries):
            log_handler.BufferedWebSocketHandler().emit(_warning())

        self.assertTrue(entries.empty())

    def test_the_worker_sends_entries_to_the_log_group(self):
        # The thread started here stays blocked on its own queue after the test, so it can't drain the module's.
        entries: queue.SimpleQueue = queue.SimpleQueue()
        layer = _RecordingChannelLayer()
        with (
            patch.object(log_handler, "_broadcast_queue", entries),
            patch.object(log_handler, "_broadcast_thread", None),
            patch("channels.layers.get_channel_layer", return_value=layer),
        ):
            log_handler.start_broadcast_worker()
            thread = log_handler._broadcast_thread
            log_handler.start_broadcast_worker()
            self.assertIs(log_handler._broadcast_thread, thread)

            log_handler.BufferedWebSocketHandler().emit(_warning("door sensor offline"))

            self.assertTrue(layer.event.wait(timeout=5))

        self.assertTrue(thread.is_alive())
        self.assertEqual(len(layer.sent), 1)
        group, message = layer.sent[0]
        self.assertEqual(group, log_handler.LOG_BROADCAST_GROUP)
        self.assertEqual(message["type"], "broadcast")
        self.assertEqual(message["message"]["type"], "log_entry")
        self.assertEqual(message["message"]["payload"]["message"], "door sensor offline")
