"""Unit tests for the in-memory ring-buffer log handler (alarm.log_handler)."""

from __future__ import annotations

import logging
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.test import SimpleTestCase

from alarm import log_handler
from alarm.log_handler import (
    BufferedWebSocketHandler,
    _broadcast_queue,
    _format_ansi,
    clear_buffer,
    configure,
    get_buffered_entries,
)


class LogHandlerTestCase(SimpleTestCase):
    """Base class that resets module-level state before each test."""

    def setUp(self):
        configure(buffer_size=500, capture_level=logging.DEBUG, broadcast_level=logging.WARNING)
        clear_buffer()
        # Drain the broadcast queue (SimpleQueue has no .clear())
        while True:
            try:
                _broadcast_queue.get_nowait()
            except (queue.Empty, Exception):
                break

    # -- helpers --

    def _make_handler(self) -> BufferedWebSocketHandler:
        return BufferedWebSocketHandler()

    def _emit_record(
        self,
        handler: BufferedWebSocketHandler,
        *,
        level: int = logging.DEBUG,
        name: str = "test.logger",
        msg: str = "test message",
    ) -> logging.LogRecord:
        record = logging.LogRecord(
            name=name,
            level=level,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        return record


class ConfigureTests(LogHandlerTestCase):
    """Tests for configure() — buffer sizing and preservation."""

    def test_configure_sets_buffer_size(self):
        configure(buffer_size=10, capture_level=logging.DEBUG, broadcast_level=logging.WARNING)
        handler = self._make_handler()
        for i in range(15):
            self._emit_record(handler, msg=f"msg-{i}")

        entries = get_buffered_entries()
        self.assertEqual(len(entries), 10)

    def test_configure_preserves_existing_entries(self):
        handler = self._make_handler()
        for i in range(3):
            self._emit_record(handler, msg=f"msg-{i}")
        self.assertEqual(len(get_buffered_entries()), 3)

        configure(buffer_size=100, capture_level=logging.DEBUG, broadcast_level=logging.WARNING)
        self.assertEqual(len(get_buffered_entries()), 3)

    def test_configure_truncates_when_shrinking(self):
        handler = self._make_handler()
        for i in range(10):
            self._emit_record(handler, msg=f"msg-{i}")
        self.assertEqual(len(get_buffered_entries()), 10)

        configure(buffer_size=3, capture_level=logging.DEBUG, broadcast_level=logging.WARNING)
        entries = get_buffered_entries()
        self.assertEqual(len(entries), 3)
        # Should keep the 3 most recent
        self.assertEqual(entries[-1]["message"], "msg-9")


class EmitTests(LogHandlerTestCase):
    """Tests for BufferedWebSocketHandler.emit()."""

    def test_emit_captures_all_fields(self):
        handler = self._make_handler()
        self._emit_record(handler, level=logging.WARNING, name="alarm.rules", msg="sensor tripped")

        entries = get_buffered_entries()
        self.assertEqual(len(entries), 1)
        entry = entries[0]

        expected_keys = {
            "timestamp", "level", "level_no", "logger", "message",
            "exc_text", "filename", "lineno", "func_name", "formatted",
        }
        self.assertEqual(set(entry.keys()), expected_keys)
        self.assertEqual(entry["level"], "WARNING")
        self.assertEqual(entry["level_no"], logging.WARNING)
        self.assertEqual(entry["logger"], "alarm.rules")
        self.assertEqual(entry["message"], "sensor tripped")

    def test_emit_respects_capture_level(self):
        configure(buffer_size=500, capture_level=logging.WARNING, broadcast_level=logging.WARNING)
        handler = self._make_handler()

        self._emit_record(handler, level=logging.DEBUG, msg="should be dropped")
        self.assertEqual(len(get_buffered_entries()), 0)

        self._emit_record(handler, level=logging.WARNING, msg="should be captured")
        self.assertEqual(len(get_buffered_entries()), 1)

    def test_emit_below_broadcast_level_skips_queue(self):
        configure(buffer_size=500, capture_level=logging.DEBUG, broadcast_level=logging.ERROR)
        handler = self._make_handler()
        self._emit_record(handler, level=logging.WARNING)

        with self.assertRaises(queue.Empty):
            _broadcast_queue.get_nowait()

    def test_emit_at_broadcast_level_enqueues(self):
        configure(buffer_size=500, capture_level=logging.DEBUG, broadcast_level=logging.WARNING)
        handler = self._make_handler()
        self._emit_record(handler, level=logging.WARNING)

        entry = _broadcast_queue.get_nowait()
        self.assertIsNotNone(entry)
        self.assertEqual(entry["level"], "WARNING")


class GetBufferedEntriesTests(LogHandlerTestCase):
    """Tests for get_buffered_entries() filtering."""

    def _populate(self, handler: BufferedWebSocketHandler):
        """Add entries at DEBUG, INFO, WARNING, ERROR levels with different loggers."""
        for level, name in [
            (logging.DEBUG, "alarm.rules.engine"),
            (logging.INFO, "alarm.sensors"),
            (logging.WARNING, "alarm.rules.parser"),
            (logging.ERROR, "alarm.actions"),
        ]:
            self._emit_record(handler, level=level, name=name, msg=f"{logging.getLevelName(level)} msg")

    def test_get_buffered_entries_unfiltered(self):
        handler = self._make_handler()
        for i in range(5):
            self._emit_record(handler, msg=f"msg-{i}")
        self.assertEqual(len(get_buffered_entries()), 5)

    def test_get_buffered_entries_filters_by_level(self):
        handler = self._make_handler()
        self._populate(handler)

        entries = get_buffered_entries(level=logging.WARNING)
        levels = {e["level"] for e in entries}
        self.assertEqual(len(entries), 2)
        self.assertEqual(levels, {"WARNING", "ERROR"})

    def test_get_buffered_entries_filters_by_logger_name(self):
        handler = self._make_handler()
        self._populate(handler)

        entries = get_buffered_entries(logger_name="alarm.rules")
        self.assertEqual(len(entries), 2)
        for e in entries:
            self.assertIn("alarm.rules", e["logger"])

    def test_get_buffered_entries_limits_results(self):
        handler = self._make_handler()
        for i in range(10):
            self._emit_record(handler, msg=f"msg-{i}")

        entries = get_buffered_entries(limit=3)
        self.assertEqual(len(entries), 3)
        # Should return the last 3
        self.assertEqual(entries[-1]["message"], "msg-9")

    def test_get_buffered_entries_combined_filters(self):
        handler = self._make_handler()
        # Add several entries at various levels with "alarm.rules" logger
        for i in range(5):
            self._emit_record(handler, level=logging.WARNING, name="alarm.rules", msg=f"w-{i}")
        for i in range(3):
            self._emit_record(handler, level=logging.ERROR, name="alarm.rules", msg=f"e-{i}")
        # Add some that should be excluded by logger filter
        self._emit_record(handler, level=logging.ERROR, name="alarm.sensors", msg="sensor-err")

        entries = get_buffered_entries(level=logging.WARNING, logger_name="alarm.rules", limit=3)
        self.assertEqual(len(entries), 3)
        for e in entries:
            self.assertIn("alarm.rules", e["logger"])
            self.assertGreaterEqual(e["level_no"], logging.WARNING)


class ClearBufferTests(LogHandlerTestCase):
    """Tests for clear_buffer()."""

    def test_clear_buffer(self):
        handler = self._make_handler()
        for i in range(5):
            self._emit_record(handler, msg=f"msg-{i}")
        self.assertEqual(len(get_buffered_entries()), 5)

        clear_buffer()
        self.assertEqual(len(get_buffered_entries()), 0)


class FormatAnsiTests(LogHandlerTestCase):
    """Tests for _format_ansi() output formatting."""

    def test_format_ansi_includes_level_color(self):
        handler = self._make_handler()
        self._emit_record(handler, level=logging.WARNING)
        entry = get_buffered_entries()[0]

        formatted = _format_ansi(entry)
        # Should contain ANSI escape codes (yellow for WARNING = \033[33m)
        self.assertIn("\033[33m", formatted)
        self.assertIn("\033[0m", formatted)  # reset code

    def test_format_ansi_includes_exception_text(self):
        entry = {
            "timestamp": "2024-01-15T10:30:45+00:00",
            "level": "ERROR",
            "level_no": logging.ERROR,
            "logger": "test",
            "message": "something failed",
            "exc_text": "Traceback (most recent call last):\n  File \"test.py\", line 1\nValueError: bad value",
            "filename": "test.py",
            "lineno": 1,
            "func_name": "test_func",
        }
        formatted = _format_ansi(entry)
        self.assertIn("Traceback", formatted)
        self.assertIn("ValueError: bad value", formatted)

    def test_format_ansi_handles_iso_timestamp(self):
        entry = {
            "timestamp": "2024-01-15T10:30:45+00:00",
            "level": "INFO",
            "level_no": logging.INFO,
            "logger": "test",
            "message": "hello",
            "exc_text": None,
            "filename": "test.py",
            "lineno": 1,
            "func_name": "test_func",
        }
        formatted = _format_ansi(entry)
        self.assertIn("10:30:45", formatted)


class BuildEntryTests(LogHandlerTestCase):
    """Tests for BufferedWebSocketHandler._build_entry()."""

    def test_build_entry_captures_exception_info(self):
        handler = self._make_handler()
        logger = logging.getLogger("test.exceptions")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        try:
            raise ValueError("test error")
        except ValueError:
            logger.error("caught an error", exc_info=True)

        entries = get_buffered_entries(logger_name="test.exceptions")
        self.assertTrue(len(entries) >= 1)
        entry = entries[-1]
        self.assertIsNotNone(entry["exc_text"])
        self.assertIn("ValueError", entry["exc_text"])
        self.assertIn("test error", entry["exc_text"])

        # Cleanup
        logger.removeHandler(handler)


class ThreadSafetyTests(LogHandlerTestCase):
    """Tests for concurrent access to the ring buffer."""

    def test_concurrent_emits_thread_safety(self):
        handler = self._make_handler()
        num_records = 100
        errors: list[Exception] = []

        def emit_one(idx: int):
            try:
                record = logging.LogRecord(
                    name="test.concurrent",
                    level=logging.INFO,
                    pathname="test.py",
                    lineno=idx,
                    msg=f"concurrent-{idx}",
                    args=(),
                    exc_info=None,
                )
                handler.emit(record)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(emit_one, i) for i in range(num_records)]
            for f in as_completed(futures):
                f.result()  # re-raise any exceptions

        self.assertEqual(len(errors), 0)
        entries = get_buffered_entries(logger_name="test.concurrent")
        self.assertEqual(len(entries), num_records)
