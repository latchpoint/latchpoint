"""Reconnect backoff for the HA state stream (#108, #114).

websocket-client's ``run_forever`` returns instead of raising when the connection is refused,
so ``_run`` has to back off after every session, not only after an exception. A session that
reaches ``auth_ok`` only resets the backoff once it has stayed up for a while, so a connection
HA drops right after auth keeps backing off too.
"""

from __future__ import annotations

import json
import socket
import threading
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations_home_assistant import state_stream
from integrations_home_assistant.state_stream import HomeAssistantStateStream, _RuntimeSettings

_SETTINGS = _RuntimeSettings(enabled=True, base_url="http://ha:8123", token="token")
_NEW_SETTINGS = _RuntimeSettings(enabled=True, base_url="http://ha-new:8123", token="new-token")


class _RecordingStopEvent:
    """Stands in for the stream's stop event: records each backoff wait instead of sleeping."""

    # Ends a loop that never waits (the #108 tight loop) so a regression fails instead of hanging.
    _MAX_LOOP_CHECKS = 100

    def __init__(self, *, max_waits: int):
        self.waits: list[float] = []
        self._max_waits = max_waits
        self._set = False
        self._checks = 0

    def is_set(self) -> bool:
        self._checks += 1
        if self._checks > self._MAX_LOOP_CHECKS:
            self._set = True
        return self._set

    def set(self) -> None:
        self._set = True

    def clear(self) -> None:
        self._set = False

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        if len(self.waits) >= self._max_waits:
            self._set = True
        return self._set


class _OtherThreadsStopEvent:
    """Sits on ``stream._stop`` so a ``_run`` that waits on it instead of its own ``stop`` fails (#132)."""

    def __getattr__(self, name: str):
        raise AssertionError(f"_run used self._stop.{name} instead of the stop event it was started with")


class _FakeClock:
    """Replaces ``state_stream._monotonic`` so session lengths don't need real time to pass."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _sessions(clock: _FakeClock, durations: list[float | None]):
    """Fake ``_connect_and_listen``: each entry is how long the session stayed up after ``auth_ok``.

    ``None`` is a session that never authed. Runs out to ``None`` once the list is used up.
    """
    remaining = iter(durations)

    def _connect(**_kwargs) -> float | None:
        duration = next(remaining, None)
        if duration is None:
            return None
        authed_at = clock.now
        clock.now += duration
        return authed_at

    return _connect


def _make_stream(*, max_waits: int) -> tuple[HomeAssistantStateStream, _RecordingStopEvent]:
    stream = HomeAssistantStateStream()
    stream._settings = _SETTINGS
    # After a restart `self._stop` belongs to the new thread, so `_run` must only use the event it's given.
    stream._stop = _OtherThreadsStopEvent()
    return stream, _RecordingStopEvent(max_waits=max_waits)


@patch.object(HomeAssistantStateStream, "_is_leader", return_value=True)
class StateStreamBackoffTests(SimpleTestCase):
    def test_return_without_auth_ok_backs_off_and_grows_to_cap(self, _leader):
        stream, stop = _make_stream(max_waits=7)
        with patch.object(stream, "_connect_and_listen", return_value=None) as connect:
            stream._run(stop)

        self.assertEqual(stop.waits, [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0])
        self.assertEqual(connect.call_count, 7)
        connect.assert_called_with(ws_url="ws://ha:8123/api/websocket", token="token", stop=stop)

    def test_connection_that_reached_auth_ok_resets_backoff(self, _leader):
        stream, stop = _make_stream(max_waits=5)
        clock = _FakeClock()
        sessions = _sessions(clock, [None, None, None, state_stream._RECONNECT_HEALTHY_SESSION_SECONDS])
        with (
            patch.object(state_stream, "_monotonic", clock),
            patch.object(stream, "_connect_and_listen", side_effect=sessions),
        ):
            stream._run(stop)

        self.assertEqual(stop.waits, [1.0, 2.0, 4.0, 1.0, 1.0])

    def test_authed_session_shorter_than_threshold_keeps_backing_off_to_cap(self, _leader):
        # The #114 flap: HA sends auth_ok and drops the connection 0.2s later, every time.
        stream, stop = _make_stream(max_waits=7)
        clock = _FakeClock()
        with (
            patch.object(state_stream, "_monotonic", clock),
            patch.object(stream, "_connect_and_listen", side_effect=_sessions(clock, [0.2] * 7)) as connect,
        ):
            stream._run(stop)

        self.assertEqual(stop.waits, [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0])
        self.assertEqual(connect.call_count, 7)

    def test_authed_session_resets_backoff_only_at_or_over_threshold(self, _leader):
        threshold = state_stream._RECONNECT_HEALTHY_SESSION_SECONDS
        # Halves keep the fake clock's float math exact right at the boundary.
        for duration in (threshold, threshold + 0.5, 3600.0):
            with self.subTest(duration=duration):
                stream, stop = _make_stream(max_waits=6)
                clock = _FakeClock()
                sessions = _sessions(clock, [None, None, threshold - 0.5, None, duration])
                with (
                    patch.object(state_stream, "_monotonic", clock),
                    patch.object(stream, "_connect_and_listen", side_effect=sessions),
                ):
                    stream._run(stop)

                # Just under the threshold counts as a failed attempt, at or over it resets.
                self.assertEqual(stop.waits, [1.0, 2.0, 4.0, 8.0, 1.0, 1.0])

    def test_healthy_session_threshold_is_patchable(self, _leader):
        # Patched above the cap, since anything below it is raised to the cap (#119).
        stream, stop = _make_stream(max_waits=4)
        clock = _FakeClock()
        with (
            patch.object(state_stream, "_RECONNECT_HEALTHY_SESSION_SECONDS", 45.0),
            patch.object(state_stream, "_monotonic", clock),
            patch.object(stream, "_connect_and_listen", side_effect=_sessions(clock, [None, None, 30.0, 45.0])),
        ):
            stream._run(stop)

        self.assertEqual(stop.waits, [1.0, 2.0, 4.0, 1.0])

    def test_healthy_session_threshold_never_goes_below_backoff_cap(self, _leader):
        # #119: with a threshold under the cap, a session that drops right after it would reset the backoff
        # and reconnect faster than the capped failure rate, so the cap wins.
        for threshold, cap in ((10.0, 30.0), (30.0, 60.0)):
            with self.subTest(threshold=threshold, cap=cap):
                stream, stop = _make_stream(max_waits=8)
                clock = _FakeClock()
                sessions = _sessions(clock, [threshold] * 7 + [cap])
                with (
                    patch.object(state_stream, "_RECONNECT_HEALTHY_SESSION_SECONDS", threshold),
                    patch.object(state_stream, "_RECONNECT_BACKOFF_MAX_SECONDS", cap),
                    patch.object(state_stream, "_monotonic", clock),
                    patch.object(stream, "_connect_and_listen", side_effect=sessions),
                ):
                    stream._run(stop)

                # Sessions that last the threshold keep backing off, only one that lasts the cap resets.
                self.assertEqual(stop.waits, [min(cap, 2.0**n) for n in range(7)] + [1.0])

    def test_exception_still_backs_off(self, _leader):
        stream, stop = _make_stream(max_waits=3)
        with (
            patch.object(stream, "_connect_and_listen", side_effect=RuntimeError("boom")),
            # The backoff must go through the stop event, never a blocking sleep.
            patch.object(state_stream.time, "sleep", side_effect=AssertionError("blocking sleep in backoff")),
        ):
            stream._run(stop)

        self.assertEqual(stop.waits, [1.0, 2.0, 4.0])

    def test_stop_during_backoff_exits_promptly(self, _leader):
        stream = HomeAssistantStateStream()
        stream._settings = _SETTINGS
        attempted = threading.Event()

        def _refused(**_kwargs) -> float | None:
            attempted.set()
            return None

        with (
            patch.object(state_stream, "_RECONNECT_BACKOFF_INITIAL_SECONDS", 60.0),
            patch.object(stream, "_connect_and_listen", side_effect=_refused) as connect,
        ):
            thread = threading.Thread(target=stream._run, args=(stream._stop,), daemon=True)
            thread.start()
            self.assertTrue(attempted.wait(timeout=5))
            stream.stop()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(connect.call_count, 1)


@patch.object(HomeAssistantStateStream, "_is_leader", return_value=False)
class StateStreamNonLeaderWaitTests(SimpleTestCase):
    """A non-leader polls for leadership (#113); that wait has to wake on `stop()` too."""

    def test_non_leader_waits_on_stop_event_not_sleep(self, _leader):
        stream, stop = _make_stream(max_waits=3)
        with (
            patch.object(stream, "_connect_and_listen") as connect,
            patch.object(state_stream.time, "sleep") as sleep,
        ):
            stream._run(stop)

        sleep.assert_not_called()
        self.assertEqual(stop.waits, [1.0, 1.0, 1.0])
        connect.assert_not_called()

    def test_stop_while_waiting_for_leadership_exits_promptly(self, leader):
        stream = HomeAssistantStateStream()
        stream._settings = _SETTINGS
        checked = threading.Event()

        def _not_leader() -> bool:
            checked.set()
            return False

        leader.side_effect = _not_leader
        with patch.object(stream, "_connect_and_listen") as connect:
            thread = threading.Thread(target=stream._run, args=(stream._stop,), daemon=True)
            thread.start()
            self.assertTrue(checked.wait(timeout=5))
            stream.stop()
            # The leadership poll is 1s, so a wait that ignores stop() would still be alive here.
            thread.join(timeout=0.5)

        self.assertFalse(thread.is_alive())
        connect.assert_not_called()


class _FakeWebSocketApp:
    """Mimics ``websocket.WebSocketApp``: ``run_forever`` replays scripted messages, then returns."""

    messages: list[dict] = []

    def __init__(self, url, *, on_open, on_message, on_error, on_close):
        self._on_message = on_message
        self._on_error = on_error
        self._on_close = on_close
        self.sent: list[str] = []

    def send(self, data: str) -> None:
        self.sent.append(data)

    def close(self) -> None:
        pass

    def run_forever(self, **_kwargs) -> bool:
        for message in self.messages:
            self._on_message(self, json.dumps(message))
        if not self.messages:
            # Refused connection: websocket-client 1.9.0 reports it via callbacks and returns.
            self._on_error(self, ConnectionRefusedError(111, "Connection refused"))
        self._on_close(self, None, None)
        return True


class ConnectAndListenAuthResultTests(SimpleTestCase):
    def _run_session(self, messages: list[dict]) -> float | None:
        stream = HomeAssistantStateStream()
        with patch.object(_FakeWebSocketApp, "messages", messages), patch("websocket.WebSocketApp", _FakeWebSocketApp):
            return stream._connect_and_listen(
                ws_url="ws://ha:8123/api/websocket", token="token", stop=threading.Event()
            )

    def test_refused_connection_returns_none(self):
        self.assertIsNone(self._run_session([]))

    def test_real_websocket_client_returns_none_on_refused_connection(self):
        # #108: the real websocket-client `run_forever` returns instead of raising when nothing is listening.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.assertFalse(5000 <= port <= 5010)

        stream = HomeAssistantStateStream()
        authed_at = stream._connect_and_listen(
            ws_url=f"ws://127.0.0.1:{port}/api/websocket", token="token", stop=threading.Event()
        )

        self.assertIsNone(authed_at)
        self.assertIsNone(stream._ws_app)

    def test_auth_invalid_returns_none(self):
        self.assertIsNone(self._run_session([{"type": "auth_required"}, {"type": "auth_invalid", "message": "bad"}]))

    def test_auth_ok_returns_monotonic_time_of_auth_ok(self):
        with patch.object(state_stream, "_monotonic", return_value=123.0):
            authed_at = self._run_session([{"type": "auth_required"}, {"type": "auth_ok"}])
        self.assertEqual(authed_at, 123.0)


class StateStreamRestartTests(SimpleTestCase):
    """``restart()`` must leave exactly one thread on the new settings (#112)."""

    def setUp(self):
        self.stream = HomeAssistantStateStream()
        self.calls: list[tuple[threading.Thread, str, threading.Event]] = []
        # Every thread this stream started, so a thread leaked by another test can't throw the checks off.
        self.threads: list[threading.Thread] = []
        self.attempts = threading.Semaphore(0)
        self.release_old = threading.Event()
        self.block_old_connect = False
        for patcher in (
            patch.object(HomeAssistantStateStream, "_is_leader", return_value=True),
            # Park each thread in its backoff wait after an attempt, until it is stopped.
            patch.object(state_stream, "_RECONNECT_BACKOFF_INITIAL_SECONDS", 60.0),
            patch.object(self.stream, "_connect_and_listen", side_effect=self._connect),
            patch.object(self.stream, "start", side_effect=self._tracking_start(self.stream.start)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self._stop_all)

    def _tracking_start(self, start):
        def _start() -> None:
            start()
            if self.stream._thread is not None and self.stream._thread not in self.threads:
                self.threads.append(self.stream._thread)

        return _start

    def _connect(self, *, ws_url, token, stop) -> float | None:
        self.calls.append((threading.current_thread(), token, stop))
        self.attempts.release()
        if self.block_old_connect and token == _SETTINGS.token:
            # A blocking TCP connect: `ws.close()` can't interrupt it, only the test can.
            self.release_old.wait(timeout=5)
        return None

    def _stop_all(self):
        self.release_old.set()
        self.stream.stop()
        for thread in self.threads:
            thread.join(timeout=5)

    def _apply(self, settings: _RuntimeSettings) -> None:
        with patch.object(state_stream, "_get_runtime_settings", return_value=settings):
            self.stream.apply_runtime_settings_from_active_profile()
        self.assertTrue(self.attempts.acquire(timeout=5))

    def test_restart_mid_backoff_leaves_one_thread_on_new_settings(self):
        self._apply(_SETTINGS)
        old_thread = self.stream._thread
        old_stop = self.stream._stop

        # The join is only an upper bound; a thread waiting in backoff exits straight away.
        with patch.object(state_stream, "_RESTART_JOIN_TIMEOUT_SECONDS", 5.0):
            self._apply(_NEW_SETTINGS)
        new_thread = self.stream._thread
        new_stop = self.stream._stop

        self.assertIsNot(new_thread, old_thread)
        self.assertIsNot(new_stop, old_stop)
        self.assertFalse(old_thread.is_alive())
        self.assertTrue(new_thread.is_alive())
        self.assertEqual(self.threads, [old_thread, new_thread])
        # Each session got the stop event of the thread that ran it.
        self.assertEqual(self.calls, [(old_thread, "token", old_stop), (new_thread, "new-token", new_stop)])

    def test_restart_when_join_times_out_starts_new_thread_and_old_one_exits(self):
        self.block_old_connect = True
        self._apply(_SETTINGS)
        old_thread = self.stream._thread
        old_stop = self.stream._stop

        with patch.object(state_stream, "_RESTART_JOIN_TIMEOUT_SECONDS", 0.01):
            self._apply(_NEW_SETTINGS)
        new_thread = self.stream._thread

        # The old thread is still stuck, but a new one is already running on the new settings.
        self.assertIsNot(new_thread, old_thread)
        self.assertTrue(old_thread.is_alive())
        self.assertTrue(new_thread.is_alive())
        self.assertTrue(old_stop.is_set())
        self.assertFalse(self.stream._stop.is_set())

        # Once unstuck, the old thread exits on its own stop event instead of reconnecting.
        self.release_old.set()
        old_thread.join(timeout=5)
        self.assertFalse(old_thread.is_alive())
        self.assertTrue(new_thread.is_alive())
        self.assertEqual(self.threads, [old_thread, new_thread])
        self.assertEqual(self.calls, [(old_thread, "token", old_stop), (new_thread, "new-token", self.stream._stop)])


class _LateStopWebSocketApp:
    """Calls ``stream.stop()`` at the top of ``run_forever``, after ``_ws_app`` is set.

    websocket-client 1.9.0 loses a ``close()`` made there: there's no socket to close yet, and
    ``run_forever`` sets ``keep_running`` back to True and connects anyway. This fake does the same,
    so ``close()`` only records the call.
    """

    stream: HomeAssistantStateStream
    instances: list[_LateStopWebSocketApp] = []

    def __init__(self, url, *, on_open, on_message, on_error, on_close):
        self._on_open = on_open
        self._on_message = on_message
        self._on_close = on_close
        self.sent: list[str] = []
        self.close_calls = 0
        self.instances.append(self)

    def send(self, data: str) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.close_calls += 1

    def run_forever(self, **_kwargs) -> bool:
        self.stream.stop()
        self._on_open(self)
        self._on_message(self, json.dumps({"type": "auth_required"}))
        self._on_message(self, json.dumps({"type": "auth_ok"}))
        self._on_close(self, None, None)
        return True


class _MustNotRunWebSocketApp(_FakeWebSocketApp):
    def run_forever(self, **_kwargs) -> bool:
        raise AssertionError("run_forever called after stop()")


class ConnectAndListenStopRaceTests(SimpleTestCase):
    """A ``stop()`` that lands while ``_connect_and_listen`` is setting up must still end the session."""

    def test_stop_before_ws_app_is_set_skips_the_session(self):
        stream = HomeAssistantStateStream()
        # stop() ran after `_run` checked the event, before `_connect_and_listen` set `_ws_app`.
        stream.stop()
        with patch("websocket.WebSocketApp", _MustNotRunWebSocketApp):
            authed_at = stream._connect_and_listen(
                ws_url="ws://ha:8123/api/websocket", token="token", stop=stream._stop
            )

        self.assertIsNone(authed_at)
        self.assertIsNone(stream._ws_app)

    def test_stop_before_run_forever_never_authenticates(self):
        stream = HomeAssistantStateStream()
        with (
            patch.object(_LateStopWebSocketApp, "stream", stream, create=True),
            patch.object(_LateStopWebSocketApp, "instances", []),
            patch("websocket.WebSocketApp", _LateStopWebSocketApp),
        ):
            # The fake's `stream.stop()` sets this event, like a real `stop()` would for this thread.
            authed_at = stream._connect_and_listen(
                ws_url="ws://ha:8123/api/websocket", token="token", stop=stream._stop
            )
            (ws_app,) = _LateStopWebSocketApp.instances

        self.assertIsNone(authed_at)
        self.assertEqual(ws_app.sent, [])
        # stop()'s close was lost, so the session closes itself once it opens.
        self.assertGreaterEqual(ws_app.close_calls, 2)


class ApplyRuntimeSettingsTests(SimpleTestCase):
    def test_settings_are_read_under_the_lock(self):
        # #132: read outside `_lock` and stored inside it, two applies at once could store the older read last.
        stream = HomeAssistantStateStream()
        held: list[bool] = []

        def _read() -> _RuntimeSettings:
            held.append(stream._lock.locked())
            return _SETTINGS

        with (
            patch.object(state_stream, "_get_runtime_settings", side_effect=_read),
            patch.object(stream, "restart") as restart,
        ):
            stream.apply_runtime_settings_from_active_profile()

        self.assertEqual(held, [True])
        self.assertEqual(stream._settings, _SETTINGS)
        restart.assert_called_once_with()
