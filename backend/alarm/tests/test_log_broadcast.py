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


class BoundedBroadcastQueueTests(SimpleTestCase):
    """The broadcast queue is bounded and drops its oldest entries when full (#174)."""

    def setUp(self):
        log_handler.configure(buffer_size=500, capture_level=logging.DEBUG, broadcast_level=logging.WARNING)
        # Keep the module's count at 0, so a worker thread left from another test has no drops to report.
        dropped = patch.object(log_handler, "_broadcast_dropped", 0)
        dropped.start()
        self.addCleanup(dropped.stop)

    def _emit_into(self, entries: queue.SimpleQueue, messages: list[str], *, maxsize: int) -> int:
        """Emit `messages` with a worker "running" but not draining. Returns how many were dropped."""
        before = log_handler.get_broadcast_dropped_count()
        with (
            patch.object(log_handler, "_broadcast_queue", entries),
            patch.object(log_handler, "_broadcast_thread", object()),
            patch.object(log_handler, "_BROADCAST_QUEUE_MAXSIZE", maxsize),
        ):
            for msg in messages:
                log_handler.BufferedWebSocketHandler().emit(_warning(msg))
        return log_handler.get_broadcast_dropped_count() - before

    @staticmethod
    def _messages(entries: queue.SimpleQueue) -> list[str]:
        return [entries.get_nowait()["message"] for _ in range(entries.qsize())]

    def test_the_module_queue_is_bounded(self):
        self.assertGreater(log_handler._BROADCAST_QUEUE_MAXSIZE, 0)

    def test_a_full_queue_drops_the_oldest_entry_and_counts_it(self):
        entries: queue.SimpleQueue = queue.SimpleQueue()

        dropped = self._emit_into(entries, ["first", "second", "third", "fourth"], maxsize=2)

        self.assertEqual(dropped, 2)
        self.assertEqual(self._messages(entries), ["third", "fourth"])

    def test_a_full_queue_still_buffers_the_entry_for_the_logs_tab(self):
        # Only the live broadcast drops. The ring buffer the Logs tab reads keeps everything up to its own size.
        log_handler.clear_buffer()

        self._emit_into(queue.SimpleQueue(), ["first", "second"], maxsize=1)

        self.assertEqual([e["message"] for e in log_handler.get_buffered_entries()], ["first", "second"])

    def test_nothing_is_dropped_below_the_limit(self):
        entries: queue.SimpleQueue = queue.SimpleQueue()

        dropped = self._emit_into(entries, ["first", "second"], maxsize=5)

        self.assertEqual(dropped, 0)
        self.assertEqual(entries.qsize(), 2)

    def test_logging_again_while_enqueueing_doesnt_deadlock(self):
        # Stands in for a signal handler that logs while this thread is inside the enqueue.
        entries: queue.SimpleQueue = queue.SimpleQueue()
        handler = log_handler.BufferedWebSocketHandler()
        original_put = entries.put_nowait
        nested: list[bool] = []

        def _put_and_log_again(entry):
            if not nested:
                nested.append(True)
                handler.emit(_warning("from a signal handler"))
            original_put(entry)

        finished = threading.Event()

        def _emit() -> None:
            with (
                patch.object(
                    log_handler, "_broadcast_queue", SimpleNamespace(qsize=entries.qsize, put_nowait=_put_and_log_again)
                ),
                patch.object(log_handler, "_broadcast_thread", object()),
            ):
                handler.emit(_warning("outer"))
            finished.set()

        threading.Thread(target=_emit, daemon=True).start()

        self.assertTrue(finished.wait(timeout=5), "the nested emit deadlocked")
        self.assertEqual(self._messages(entries), ["from a signal handler", "outer"])


class DroppedBroadcastReportTests(SimpleTestCase):
    """The worker logs dropped broadcasts at most once a minute (#174)."""

    def setUp(self):
        for name, value in (("_broadcast_dropped", 0), ("_drops_reported", 0), ("_drops_reported_at", None)):
            p = patch.object(log_handler, name, value)
            p.start()
            self.addCleanup(p.stop)

    def _report(self, *, now: float) -> list[str]:
        with self.assertLogs("alarm.log_handler", level="WARNING") as logs:
            logging.getLogger("alarm.log_handler").warning("marker")
            log_handler._report_drops(now=now)
        return [r.getMessage() for r in logs.records if r.getMessage() != "marker"]

    def test_reports_new_drops_once_then_waits_a_minute(self):
        log_handler._broadcast_dropped = 3
        self.assertEqual(
            self._report(now=100.0),
            [
                "Dropped 3 log entries from the live log stream because the broadcast queue was full (3 since start). "
                "Debug > Logs still has them up to its buffer size."
            ],
        )

        log_handler._broadcast_dropped = 5
        self.assertEqual(self._report(now=130.0), [])

        reported = self._report(now=161.0)
        self.assertEqual(len(reported), 1)
        self.assertIn("Dropped 2 log entries", reported[0])
        self.assertIn("(5 since start)", reported[0])

    def test_stays_quiet_without_new_drops(self):
        self.assertEqual(self._report(now=100.0), [])

        log_handler._broadcast_dropped = 1
        self._report(now=200.0)
        self.assertEqual(self._report(now=400.0), [])

    def test_the_worker_reports_while_idle(self):
        # A burst that ended still gets reported, from the worker's own timeout. The second `get` ends the loop.
        class _Stop(Exception):
            pass

        timeouts: list[float] = []

        def _get(timeout):
            timeouts.append(timeout)
            if len(timeouts) == 1:
                raise queue.Empty
            raise _Stop

        with patch.object(log_handler, "_report_drops") as report, self.assertRaises(_Stop):
            log_handler._broadcast_worker(SimpleNamespace(get=_get))

        report.assert_called_once_with()
        self.assertEqual(timeouts, [log_handler._DROP_REPORT_INTERVAL_SECONDS] * 2)
