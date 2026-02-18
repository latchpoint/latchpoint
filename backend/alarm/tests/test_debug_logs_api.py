"""REST API tests for the DebugLogsView endpoint (debug_logs.py)."""

from __future__ import annotations

import logging
import queue

from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from alarm import log_handler
from alarm.log_handler import BufferedWebSocketHandler, _broadcast_queue, clear_buffer, configure


class DebugLogsApiTestCase(APITestCase):
    """Base class that sets up users and resets the log buffer."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(
            email="admin@example.com", password="pass", is_staff=True
        )
        cls.regular_user = User.objects.create_user(
            email="user@example.com", password="pass", is_staff=False
        )

    def setUp(self):
        configure(buffer_size=500, capture_level=logging.DEBUG, broadcast_level=logging.WARNING)
        clear_buffer()
        while True:
            try:
                _broadcast_queue.get_nowait()
            except (queue.Empty, Exception):
                break

    def _get_url(self):
        return reverse("debug-logs")

    def _populate_buffer(self):
        """Emit records at various levels/loggers directly via the handler."""
        handler = BufferedWebSocketHandler()
        for level, name in [
            (logging.DEBUG, "alarm.rules.engine"),
            (logging.INFO, "alarm.sensors"),
            (logging.WARNING, "alarm.rules.parser"),
            (logging.ERROR, "alarm.actions"),
            (logging.CRITICAL, "alarm.core"),
        ]:
            record = logging.LogRecord(
                name=name,
                level=level,
                pathname="test.py",
                lineno=1,
                msg=f"{logging.getLevelName(level)} message from {name}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)


class DebugLogsGetTests(DebugLogsApiTestCase):
    """Tests for GET /api/alarm/debug/logs/."""

    def test_get_requires_authentication(self):
        response = self.client.get(self._get_url())
        self.assertEqual(response.status_code, 401)

    def test_get_requires_admin(self):
        self.client.force_authenticate(self.regular_user)
        response = self.client.get(self._get_url())
        self.assertEqual(response.status_code, 403)

    def test_get_returns_entries_for_admin(self):
        self._populate_buffer()
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(self._get_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 5)

    def test_get_filters_by_level_param(self):
        self._populate_buffer()
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(self._get_url(), {"level": "ERROR"})
        self.assertEqual(response.status_code, 200)
        levels = {e["level"] for e in response.data}
        self.assertTrue(levels <= {"ERROR", "CRITICAL"})
        self.assertTrue(len(response.data) >= 1)

    def test_get_filters_by_logger_param(self):
        self._populate_buffer()
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(self._get_url(), {"logger": "alarm.rules"})
        self.assertEqual(response.status_code, 200)
        for entry in response.data:
            self.assertIn("alarm.rules", entry["logger"])

    def test_get_filters_by_limit_param(self):
        self._populate_buffer()
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(self._get_url(), {"limit": "3"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 3)

    def test_get_ignores_invalid_level(self):
        self._populate_buffer()
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(self._get_url(), {"level": "NONEXISTENT"})
        self.assertEqual(response.status_code, 200)
        # Invalid level is silently ignored — all entries returned
        self.assertEqual(len(response.data), 5)

    def test_get_ignores_invalid_limit(self):
        self._populate_buffer()
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(self._get_url(), {"limit": "abc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 5)


class DebugLogsDeleteTests(DebugLogsApiTestCase):
    """Tests for DELETE /api/alarm/debug/logs/."""

    def test_delete_requires_authentication(self):
        response = self.client.delete(self._get_url())
        self.assertEqual(response.status_code, 401)

    def test_delete_requires_admin(self):
        self.client.force_authenticate(self.regular_user)
        response = self.client.delete(self._get_url())
        self.assertEqual(response.status_code, 403)

    def test_delete_clears_buffer(self):
        self._populate_buffer()
        self.client.force_authenticate(self.admin_user)

        response = self.client.delete(self._get_url())
        self.assertEqual(response.status_code, 204)

        response = self.client.get(self._get_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)
