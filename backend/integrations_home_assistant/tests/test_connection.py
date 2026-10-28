from __future__ import annotations

import threading
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations_home_assistant import connection
from integrations_home_assistant.connection import (
    clear_cached_connection,
    get_cached_connection,
    set_cached_connection,
)
from integrations_home_assistant.tests.stream_test_utils import RecordingLock

_OLD = {"enabled": True, "base_url": "http://ha:8123", "token": "token"}
_NEW = {"enabled": True, "base_url": "http://ha-new:8123", "token": "new-token"}


class SetCachedConnectionTests(SimpleTestCase):
    def setUp(self):
        clear_cached_connection()
        self.addCleanup(clear_cached_connection)

    def test_overlapping_saves_keep_the_newer_settings(self):
        # #141: save A reads the old settings, save B reads and stores the new ones, then A stores the old ones on
        # top. Reading inside the lock makes B wait for A, so B's read is the one that's stored last.
        db = {"value": _OLD}
        a_read = threading.Event()
        release_a = threading.Event()

        def _get_ha_settings() -> dict:
            value = db["value"]
            if threading.current_thread() is save_a:
                a_read.set()
                release_a.wait(timeout=5)
            return value

        save_a = threading.Thread(target=set_cached_connection, daemon=True)
        save_b = threading.Thread(target=set_cached_connection, daemon=True)
        refresh_lock = RecordingLock()
        with (
            patch("integrations_home_assistant.views.get_ha_settings", side_effect=_get_ha_settings),
            patch.object(connection, "_refresh_lock", refresh_lock),
        ):
            save_a.start()
            self.assertTrue(a_read.wait(timeout=5))
            # Save B commits the new settings while A still holds its older read.
            db["value"] = _NEW
            save_b.start()
            refresh_lock.wait_until_tried(save_b)
            release_a.set()
            save_a.join(timeout=5)
            save_b.join(timeout=5)

        self.assertFalse(save_a.is_alive())
        self.assertFalse(save_b.is_alive())
        cached = get_cached_connection()
        self.assertEqual((cached.base_url, cached.token), ("http://ha-new:8123", "new-token"))

    def test_cache_readers_dont_wait_on_the_settings_read(self):
        # The read holds `_refresh_lock`, not `_lock`, so the gateway can still read the cache meanwhile.
        held: list[bool] = []

        def _get_ha_settings() -> dict:
            held.append(connection._lock.locked())
            return _NEW

        with patch("integrations_home_assistant.views.get_ha_settings", side_effect=_get_ha_settings):
            set_cached_connection()

        self.assertEqual(held, [False])
        self.assertEqual(get_cached_connection().token, "new-token")

    def test_failed_read_keeps_the_cached_settings(self):
        with patch("integrations_home_assistant.views.get_ha_settings", return_value=_OLD):
            set_cached_connection()
        with patch("integrations_home_assistant.views.get_ha_settings", side_effect=RuntimeError("db down")):
            set_cached_connection()

        self.assertEqual(get_cached_connection().token, "token")
        self.assertFalse(connection._refresh_lock.locked())
