"""The device mapping refresh runs from the on-connect hook, and only when Zigbee2MQTT is enabled (#164)."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations_zigbee2mqtt import runtime


class _FakeMqttManager:
    def __init__(self) -> None:
        self.hooks: list = []

    def register_on_connect(self, callback) -> None:
        self.hooks.append(callback)


class InitializeMappingRefreshTests(SimpleTestCase):
    def _initialize(self, *, enabled: bool) -> tuple[_FakeMqttManager, object]:
        fake = _FakeMqttManager()
        patches = (
            patch.object(runtime, "_initialized", False),
            patch.object(runtime, "mqtt_connection_manager", fake),
            patch.object(runtime, "get_settings", return_value=SimpleNamespace(enabled=enabled)),
            patch.object(runtime, "_mqtt_enabled", return_value=True),
            patch.object(runtime, "_subscribe_for_ingest"),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        refresh_patch = patch.object(runtime, "refresh_device_mapping_async")
        refresh = refresh_patch.start()
        self.addCleanup(refresh_patch.stop)

        runtime.initialize()
        return fake, refresh

    def test_doesnt_refresh_before_mqtt_connects(self):
        # The server's startup runs before MQTT connects, where a refresh can only fail to publish and log a
        # traceback. The hook refreshes once it connects (or right away, if it already has).
        fake, refresh = self._initialize(enabled=True)

        refresh.assert_not_called()
        self.assertEqual(len(fake.hooks), 1)

    def test_the_hook_refreshes_when_enabled(self):
        fake, refresh = self._initialize(enabled=True)

        fake.hooks[0]()

        refresh.assert_called_once()

    def test_the_hook_skips_when_disabled(self):
        fake, refresh = self._initialize(enabled=False)

        fake.hooks[0]()

        refresh.assert_not_called()


class _FakeTimer:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class MappingRefreshTimeoutTests(SimpleTestCase):
    """A devices request that times out logs one line and retries on a timer (#174)."""

    def setUp(self):
        self.timers: list[_FakeTimer] = []
        self.connected = True

        def _start(delay, callback):
            timer = _FakeTimer(delay, callback)
            self.timers.append(timer)
            return timer

        fake_mqtt = SimpleNamespace(get_status=lambda: SimpleNamespace(connected=self.connected))
        patches = (
            patch.object(runtime, "_mapping_retry_timer", None),
            patch.object(runtime, "_mapping_retry_delay", runtime._MAPPING_RETRY_INITIAL_SECONDS),
            patch.object(runtime, "_start_mapping_retry_timer", side_effect=_start),
            patch.object(runtime, "get_settings", return_value=SimpleNamespace(enabled=True)),
            patch.object(runtime, "_mqtt_enabled", return_value=True),
            patch.object(runtime, "mqtt_connection_manager", fake_mqtt),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _timeout(self) -> TimeoutError:
        return TimeoutError("Timed out waiting for Zigbee2MQTT devices response.")

    def _run(self, fn, *, error: Exception | None = None) -> list:
        """Run `fn` with the devices request failing with `error` (or succeeding). Returns the WARNINGs logged."""
        with (
            patch.object(runtime, "refresh_device_mapping_via_mqtt", side_effect=error) as refresh,
            self.assertLogs(runtime.logger, level="WARNING") as logs,
        ):
            runtime.logger.warning("marker")
            fn()
        self.refresh_calls = refresh.call_count
        return [r for r in logs.records if r.getMessage() != "marker"]

    def _refresh(self, *, error: Exception | None = None) -> list:
        return self._run(runtime._refresh_device_mapping, error=error)

    def test_the_hooks_refresh_logs_a_timeout_as_one_line(self):
        # Through `refresh_device_mapping_async`, which the on-connect hook calls at boot, with its thread run inline.
        runtime.cache.delete(runtime._CACHE_KEY_LAST_MAPPING_REFRESH_AT)
        inline = SimpleNamespace(Thread=lambda target, daemon: SimpleNamespace(start=target))
        with patch.object(runtime, "threading", inline):
            records = self._run(runtime.refresh_device_mapping_async, error=self._timeout())

        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].exc_info)
        self.assertEqual([t.delay for t in self.timers], [30])

    def test_a_timeout_logs_one_line_without_a_traceback(self):
        records = self._refresh(error=self._timeout())

        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].exc_info)
        self.assertEqual(
            records[0].getMessage(),
            "Device mapping refresh failed: Timed out waiting for Zigbee2MQTT devices response. Retrying in 30s.",
        )

    def test_a_timeout_schedules_one_retry_that_backs_off(self):
        self._refresh(error=self._timeout())
        self.assertEqual([t.delay for t in self.timers], [30])

        # A second failure (ie from the on-connect hook) while the retry is pending doesn't add another timer.
        self._refresh(error=self._timeout())
        self.assertEqual([t.delay for t in self.timers], [30])

        self._run(self.timers[0].callback, error=self._timeout())
        self.assertEqual([t.delay for t in self.timers], [30, 60])

    def test_the_backoff_is_capped(self):
        for _ in range(10):
            self._run(runtime._retry_mapping_refresh, error=self._timeout())

        self.assertEqual(self.timers[-1].delay, runtime._MAPPING_RETRY_MAX_SECONDS)

    def test_the_retry_refreshes_again_and_a_success_resets_the_backoff(self):
        self._refresh(error=self._timeout())

        self._run(self.timers[0].callback)
        self.assertEqual(self.refresh_calls, 1)

        self._refresh(error=self._timeout())
        self.assertEqual([t.delay for t in self.timers], [30, 30])

    def test_a_success_cancels_a_pending_retry(self):
        self._refresh(error=self._timeout())

        self._refresh()

        self.assertTrue(self.timers[0].cancelled)
        self.assertIsNone(runtime._mapping_retry_timer)

    def test_the_retry_waits_for_the_next_connect_when_mqtt_is_down(self):
        # The on-connect hook refreshes once MQTT is back, so the timer doesn't publish into a dead connection.
        self._refresh(error=self._timeout())
        self.connected = False

        self._run(self.timers[0].callback)

        self.assertEqual(self.refresh_calls, 0)
        self.assertEqual(len(self.timers), 1)

    def test_the_retry_stops_when_zigbee2mqtt_is_disabled(self):
        self._refresh(error=self._timeout())

        with patch.object(runtime, "get_settings", return_value=SimpleNamespace(enabled=False)):
            self._run(self.timers[0].callback)

        self.assertEqual(self.refresh_calls, 0)
        self.assertEqual(len(self.timers), 1)

    def test_other_errors_still_log_the_traceback(self):
        records = self._refresh(error=RuntimeError("bad payload"))

        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].exc_info)
        self.assertEqual(self.timers, [])


class MappingRetryTimerTests(SimpleTestCase):
    def test_runs_the_callback_once_on_a_daemon_thread(self):
        fired = threading.Event()

        timer = runtime._start_mapping_retry_timer(0.01, fired.set)

        self.assertTrue(fired.wait(timeout=5))
        self.assertTrue(timer.daemon)
