"""Reconnect backoff for the HA state stream (#108, #114).

websocket-client's ``run_forever`` returns instead of raising when the connection is refused,
so ``_run`` has to back off after every session, not only after an exception. A session that
reaches ``auth_ok`` only resets the backoff once it has stayed up for a while, so a connection
HA drops right after auth keeps backing off too.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations_home_assistant import state_stream
from integrations_home_assistant.state_stream import HomeAssistantStateStream, _RuntimeSettings
from integrations_home_assistant.tests.stream_test_utils import FakeSessionStream, RecordingLock

_SETTINGS = _RuntimeSettings(enabled=True, base_url="http://ha:8123", token="token")
_NEW_SETTINGS = _RuntimeSettings(enabled=True, base_url="http://ha-new:8123", token="new-token")
_DISABLED = _RuntimeSettings(enabled=False, base_url="", token="")


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


class _NoSleepTime:
    """Stands in for ``state_stream.time`` so only the stream's own sleeps are caught, not the whole process's."""

    def __init__(self):
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        raise AssertionError("blocking time.sleep in the state stream")

    def __getattr__(self, name: str):
        return getattr(time, name)


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
        sessions = _sessions(clock, [None, None, None, state_stream._healthy_session_seconds()])
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
        threshold = state_stream._healthy_session_seconds()
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
        no_sleep = _NoSleepTime()
        with (
            patch.object(stream, "_connect_and_listen", side_effect=RuntimeError("boom")),
            # The backoff must go through the stop event, never a blocking sleep.
            patch.object(state_stream, "time", no_sleep),
        ):
            stream._run(stop)

        self.assertEqual(no_sleep.sleeps, [])
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
        no_sleep = _NoSleepTime()
        with (
            patch.object(stream, "_connect_and_listen") as connect,
            patch.object(state_stream, "time", no_sleep),
        ):
            stream._run(stop)

        self.assertEqual(no_sleep.sleeps, [])
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
        stream = HomeAssistantStateStream()
        result: dict[str, object] = {}

        def _connect() -> None:
            try:
                result["authed_at"] = stream._connect_and_listen(
                    ws_url=f"ws://127.0.0.1:{port}/api/websocket", token="token", stop=threading.Event()
                )
            except BaseException as exc:
                result["error"] = exc

        # websocket-client 1.9.0 sends 127.0.0.1 through `http_proxy` too, so make sure it connects directly.
        proxy_env = {"no_proxy": "*", "NO_PROXY": "*"}
        with patch.dict(os.environ, proxy_env), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
                os.environ.pop(name, None)
            # Bound but never listening: the connect is refused straight away and nothing else can take the port.
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            thread = threading.Thread(target=_connect, daemon=True)
            thread.start()
            # A regression that hangs (or a proxy that never answers) fails here instead of hanging the run.
            thread.join(timeout=5)

        self.assertFalse(thread.is_alive(), "_connect_and_listen didn't return on a refused connection")
        self.assertNotIn("error", result)
        self.assertIsNone(result["authed_at"])
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
    """Sets the session's stop event at the top of ``run_forever``, after ``_ws_app`` is set.

    That's a ``stop()`` landing there. websocket-client 1.9.0 loses the ``close()`` it makes at that
    point (there's no socket to close yet, and ``run_forever`` sets ``keep_running`` back to True and
    connects anyway), so only the session's own stop checks can end it. ``close()`` only records the call.
    """

    stop: threading.Event
    instances: list[_LateStopWebSocketApp] = []

    def __init__(self, url, *, on_open, on_message, on_error, on_close):
        self._on_open = on_open
        self._on_message = on_message
        self._on_close = on_close
        self.sent: list[str] = []
        self.close_calls = 0
        self.close_calls_after_open: int | None = None
        self.instances.append(self)

    def send(self, data: str) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.close_calls += 1

    def run_forever(self, **_kwargs) -> bool:
        self.stop.set()
        self._on_open(self)
        self.close_calls_after_open = self.close_calls
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
        # This thread was stopped after `_run` checked the event, before `_connect_and_listen` set `_ws_app`.
        # `stream._stop` stays clear, so only a check on the session's own event skips the connect.
        stop = threading.Event()
        stop.set()
        with patch("websocket.WebSocketApp", _MustNotRunWebSocketApp):
            authed_at = stream._connect_and_listen(ws_url="ws://ha:8123/api/websocket", token="token", stop=stop)

        self.assertIsNone(authed_at)
        self.assertIsNone(stream._ws_app)
        self.assertFalse(stream._stop.is_set())

    def test_stop_before_run_forever_never_authenticates(self):
        stream = HomeAssistantStateStream()
        # The fake sets this event, not `stream._stop`, so only checks on the session's own event end it.
        stop = threading.Event()
        with (
            patch.object(_LateStopWebSocketApp, "stop", stop, create=True),
            patch.object(_LateStopWebSocketApp, "instances", []),
            patch("websocket.WebSocketApp", _LateStopWebSocketApp),
        ):
            authed_at = stream._connect_and_listen(ws_url="ws://ha:8123/api/websocket", token="token", stop=stop)
            (ws_app,) = _LateStopWebSocketApp.instances

        self.assertIsNone(authed_at)
        self.assertEqual(ws_app.sent, [])
        # stop()'s close was lost, so the session closes itself as soon as it opens, before HA says anything.
        self.assertEqual(ws_app.close_calls_after_open, 1)
        self.assertFalse(stream._stop.is_set())


class ApplyRuntimeSettingsTests(SimpleTestCase):
    def test_settings_are_read_under_the_apply_lock_but_not_the_stream_lock(self):
        # #132: read outside the lock and stored inside it, two applies at once could store the older read last.
        # #121: the read can hit the DB on a cold cache, so it stays out of `_lock`, which `stop()` and the
        # stream thread use.
        stream = HomeAssistantStateStream()
        held: list[tuple[bool, bool]] = []

        def _read() -> _RuntimeSettings:
            held.append((stream._apply_lock.locked(), stream._lock.locked()))
            return _SETTINGS

        with (
            patch.object(state_stream, "_get_runtime_settings", side_effect=_read),
            patch.object(stream, "restart") as restart,
        ):
            stream.apply_runtime_settings_from_active_profile()

        self.assertEqual(held, [(True, False)])
        self.assertEqual(stream._settings, _SETTINGS)
        restart.assert_called_once_with()

    def test_stop_restart_and_start_run_under_the_apply_lock(self):
        stream = HomeAssistantStateStream()
        held: list[tuple[str, bool]] = []

        def _record(method: str):
            return lambda: held.append((method, stream._apply_lock.locked()))

        for settings, method in ((_SETTINGS, "restart"), (_SETTINGS, "start"), (_DISABLED, "stop")):
            with (
                self.subTest(method=method),
                patch.object(state_stream, "_get_runtime_settings", return_value=settings),
                patch.object(stream, method, side_effect=_record(method)),
            ):
                stream.apply_runtime_settings_from_active_profile()

        self.assertEqual(held, [("restart", True), ("start", True), ("stop", True)])


class ConcurrentApplyTests(SimpleTestCase):
    """Two applies at once must end with the stream running on the newer settings (#121)."""

    def test_older_apply_cant_stop_the_stream_after_a_newer_one_restarts_it(self):
        fake = FakeSessionStream(self)
        stream = fake.stream
        stream._apply_lock = RecordingLock()
        with patch.object(state_stream, "_get_runtime_settings", return_value=_SETTINGS):
            stream.apply_runtime_settings_from_active_profile()
        fake.wait_for_session()

        # Apply A reads "disabled" and is about to stop the stream when apply B reads the newer, enabled settings.
        reads = iter([_DISABLED, _NEW_SETTINGS])
        a_stopping = threading.Event()
        release_a = threading.Event()
        real_stop = stream.stop

        def _stop():
            if threading.current_thread() is apply_a:
                a_stopping.set()
                release_a.wait(timeout=5)
            return real_stop()

        apply_a = threading.Thread(target=stream.apply_runtime_settings_from_active_profile, daemon=True)
        apply_b = threading.Thread(target=stream.apply_runtime_settings_from_active_profile, daemon=True)
        with (
            patch.object(state_stream, "_get_runtime_settings", side_effect=lambda: next(reads)),
            patch.object(stream, "stop", side_effect=_stop),
        ):
            apply_a.start()
            self.assertTrue(a_stopping.wait(timeout=5))
            apply_b.start()
            # Without the apply lock B restarts the stream here, and A's stop then lands on B's new thread.
            stream._apply_lock.wait_until_tried(apply_b)
            release_a.set()
            apply_a.join(timeout=5)
            apply_b.join(timeout=5)
            self.assertFalse(apply_a.is_alive())
            self.assertFalse(apply_b.is_alive())

        thread, ws_url, token, stop = fake.wait_for_session()
        self.assertEqual(stream._settings, _NEW_SETTINGS)
        self.assertIs(thread, stream._thread)
        self.assertTrue(thread.is_alive())
        self.assertFalse(stop.is_set())
        self.assertEqual((ws_url, token), ("ws://ha-new:8123/api/websocket", "new-token"))


class _RequestOnWorkerExitLock:
    """Stands in for ``_apply_worker_lock``, and makes one request on another thread right after the worker
    releases it on its way out (its first release once it has applied once and nothing is queued)."""

    def __init__(self, stream: HomeAssistantStateStream, applies: list[threading.Thread]):
        self._lock = threading.Lock()
        self._stream = stream
        self._applies = applies
        self._fired = False
        self.request_made = threading.Event()

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, *exc):
        result = self._lock.__exit__(*exc)
        worker_exiting = (
            threading.current_thread().name == "ha-state-stream-apply"
            and len(self._applies) == 1
            and not self._stream._apply_requested
        )
        if worker_exiting and not self._fired:
            self._fired = True
            requester = threading.Thread(target=self._stream.apply_runtime_settings_in_background, daemon=True)
            requester.start()
            requester.join(timeout=5)
            self.request_made.set()
        return result


class BackgroundApplyTests(SimpleTestCase):
    def test_returns_right_away_and_coalesces_requests_into_one_more_apply(self):
        fake = FakeSessionStream(self)
        stream = fake.stream
        current = {"settings": _SETTINGS}
        reads: list[_RuntimeSettings] = []
        first_read_started = threading.Event()
        release_first_read = threading.Event()

        def _read() -> _RuntimeSettings:
            settings = current["settings"]
            reads.append(settings)
            if len(reads) == 1:
                first_read_started.set()
                release_first_read.wait(timeout=5)
            return settings

        with patch.object(state_stream, "_get_runtime_settings", side_effect=_read):
            stream.apply_runtime_settings_in_background()
            # The call returned while the apply it queued is still blocked.
            self.assertTrue(first_read_started.wait(timeout=5))
            current["settings"] = _NEW_SETTINGS
            for _ in range(3):
                stream.apply_runtime_settings_in_background()
            self.assertFalse(stream.wait_for_background_apply(timeout=0))
            release_first_read.set()
            self.assertTrue(stream.wait_for_background_apply(timeout=5))

        # The three requests made during the first apply ran as one more apply, on the newest settings.
        self.assertEqual(reads, [_SETTINGS, _NEW_SETTINGS])
        self.assertEqual(stream._settings, _NEW_SETTINGS)
        self.assertIsNone(stream._apply_worker)
        # The first apply's thread may already have seen the new settings or been stopped before connecting,
        # so only the current thread's session is checked.
        thread, _, token, stop = fake.wait_for_current_session()
        self.assertEqual(token, "new-token")
        self.assertTrue(thread.is_alive())
        self.assertFalse(stop.is_set())

    def test_request_after_the_worker_finishes_starts_a_new_apply(self):
        stream = HomeAssistantStateStream()
        with patch.object(stream, "apply_runtime_settings_from_active_profile") as apply:
            stream.apply_runtime_settings_in_background()
            self.assertTrue(stream.wait_for_background_apply(timeout=5))
            stream.apply_runtime_settings_in_background()
            self.assertTrue(stream.wait_for_background_apply(timeout=5))

        self.assertEqual(apply.call_count, 2)

    def test_closes_db_connections_around_the_apply(self):
        stream = HomeAssistantStateStream()
        calls: list[str] = []
        applying = threading.Event()
        release = threading.Event()

        def _apply() -> None:
            calls.append("apply")
            applying.set()
            release.wait(timeout=5)

        with (
            patch.object(state_stream, "close_old_connections", side_effect=lambda: calls.append("close_old")),
            patch.object(state_stream, "connections") as connections,
            patch.object(stream, "apply_runtime_settings_from_active_profile", side_effect=_apply),
        ):
            connections.close_all.side_effect = lambda: calls.append("close_all")
            stream.apply_runtime_settings_in_background()
            self.assertTrue(applying.wait(timeout=5))
            worker = stream._apply_worker
            release.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(calls, ["close_old", "apply", "close_all"])

    def test_failed_db_cleanup_on_a_later_pass_still_applies_and_finishes(self):
        # The second pass has already taken its request, so a raise there must not skip the apply or kill the
        # worker before it gives up `_apply_worker` and sets `_apply_idle`.
        stream = HomeAssistantStateStream()
        applies: list[threading.Thread] = []
        first_applying = threading.Event()
        release_first = threading.Event()

        def _apply() -> None:
            applies.append(threading.current_thread())
            if len(applies) == 1:
                first_applying.set()
                release_first.wait(timeout=5)

        with (
            patch.object(state_stream, "close_old_connections", side_effect=[None, RuntimeError("db gone")]),
            patch.object(state_stream, "connections"),
            patch.object(stream, "apply_runtime_settings_from_active_profile", side_effect=_apply),
            self.assertLogs("integrations_home_assistant", level="WARNING") as logs,
        ):
            stream.apply_runtime_settings_in_background()
            self.assertTrue(first_applying.wait(timeout=5))
            worker = stream._apply_worker
            # Queued while the first apply runs, so it's taken on the pass where the cleanup raises.
            stream.apply_runtime_settings_in_background()
            release_first.set()
            self.assertTrue(stream.wait_for_background_apply(timeout=5))
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(applies, [worker, worker])
        self.assertIsNone(stream._apply_worker)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("closing stale DB connections failed", logs.output[0])

    def test_request_landing_as_the_worker_exits_still_runs(self):
        # The worker's exit has to give up `_apply_worker` under the same lock hold as its "nothing requested"
        # check. This forces a request in right after the worker releases that lock on its way out, which is
        # where a request would be dropped if `_apply_worker` were cleared after the lock.
        stream = HomeAssistantStateStream()
        applies: list[threading.Thread] = []
        lock = _RequestOnWorkerExitLock(stream, applies)
        stream._apply_worker_lock = lock
        with patch.object(
            stream,
            "apply_runtime_settings_from_active_profile",
            side_effect=lambda: applies.append(threading.current_thread()),
        ):
            stream.apply_runtime_settings_in_background()
            self.assertTrue(lock.request_made.wait(timeout=5))
            self.assertTrue(stream.wait_for_background_apply(timeout=5))

        self.assertEqual(len(applies), 2)
        self.assertFalse(stream._apply_requested)
        self.assertIsNone(stream._apply_worker)

    def test_failed_apply_is_logged_and_the_worker_still_finishes(self):
        stream = HomeAssistantStateStream()
        with (
            patch.object(stream, "apply_runtime_settings_from_active_profile", side_effect=RuntimeError("boom")),
            self.assertLogs("integrations_home_assistant", level="WARNING") as logs,
        ):
            stream.apply_runtime_settings_in_background()
            self.assertTrue(stream.wait_for_background_apply(timeout=5))

        self.assertIn("HA state stream apply failed", logs.output[0])
        self.assertIsNone(stream._apply_worker)
