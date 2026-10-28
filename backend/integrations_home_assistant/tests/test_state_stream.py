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


# Taken before any test patches it, for tests that need the real one under `FakeSessionStream`.
_real_is_leader = HomeAssistantStateStream._is_leader


class _FakeSharedCache:
    """
    A cache shared between workers, with the leader key's TTL running on a fake clock.

    Covers the part of Django's cache API the leader key uses. ``on_get`` runs right after a ``get()``, so a
    test can land something between the get and whatever the caller does next.
    """

    def __init__(self, clock: _FakeClock):
        self._clock = clock
        self._lock = threading.Lock()
        self._data: dict[str, tuple[object, float]] = {}
        self.touches = 0
        self.deletes = 0
        self.on_get = None

    def _live(self, key: str) -> tuple[object, float] | None:
        item = self._data.get(key)
        if item is not None and item[1] <= self._clock():
            del self._data[key]
            return None
        return item

    def add(self, key: str, value: object, timeout: float) -> bool:
        with self._lock:
            if self._live(key) is not None:
                return False
            self._data[key] = (value, self._clock() + timeout)
            return True

    def get(self, key: str) -> object:
        with self._lock:
            item = self._live(key)
        if self.on_get is not None:
            self.on_get()
        return None if item is None else item[0]

    def touch(self, key: str, timeout: float) -> bool:
        with self._lock:
            item = self._live(key)
            if item is None:
                return False
            self._data[key] = (item[0], self._clock() + timeout)
            self.touches += 1
            return True

    def delete(self, key: str) -> bool:
        with self._lock:
            self.deletes += 1
            return self._data.pop(key, None) is not None

    def set(self, key: str, value: object, timeout: float) -> None:
        with self._lock:
            self._data[key] = (value, self._clock() + timeout)

    def owner(self) -> object:
        with self._lock:
            item = self._live(state_stream._CACHE_LEADER_KEY)
        return None if item is None else item[0]


class _FailingCache:
    def __getattr__(self, name: str):
        def _fail(*_args, **_kwargs):
            raise ConnectionError("cache is down")

        return _fail


class _SessionTimeline:
    """
    Stands in for a session's ``session_done`` event, so a long session runs on the fake clock.

    Each ``wait(timeout)`` moves the clock forward a second at a time and calls ``every_second`` after each
    step (another worker polling for leadership, say). Returns True once the session has lasted ``duration``.
    """

    def __init__(self, clock: _FakeClock, *, duration: float, every_second=None):
        self.waits: list[float] = []
        self._clock = clock
        self._end = clock.now + duration
        self._every_second = every_second or (lambda: None)

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        for _ in range(int(timeout)):
            if self._clock.now >= self._end:
                return True
            self._clock.now += 1.0
            self._every_second()
        return self._clock.now >= self._end


class _ClosableWebSocketApp:
    def __init__(self):
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class LeaderRenewalTests(SimpleTestCase):
    """A session keeps the leader key for as long as it runs, and gives up once another worker has it (#118)."""

    def setUp(self):
        self.clock = _FakeClock()
        self.cache = _FakeSharedCache(self.clock)
        patcher = patch.object(state_stream, "cache", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.leader = HomeAssistantStateStream()
        self.other = HomeAssistantStateStream()

    def _renew(self, timeline: _SessionTimeline, stop: threading.Event | None = None):
        ws_app = _ClosableWebSocketApp()
        lost = threading.Event()
        self.leader._renew_leadership_during_session(
            ws_app=ws_app, stop=stop or threading.Event(), session_done=timeline, lost=lost
        )
        return ws_app, lost

    def test_long_session_renews_the_key_before_it_expires(self):
        # `_run` takes the key right before the session starts.
        self.assertTrue(self.leader._is_leader())
        other_won: list[float] = []

        def _other_polls() -> None:
            # A non-leader polls every second, so it would get in the moment the key ran out.
            if self.other._is_leader():
                other_won.append(self.clock.now)

        # Ten times the TTL.
        duration = 10 * state_stream._LEADER_TTL_SECONDS
        timeline = _SessionTimeline(self.clock, duration=duration, every_second=_other_polls)
        ws_app, lost = self._renew(timeline)

        self.assertEqual(other_won, [])
        self.assertEqual(self.cache.owner(), self.leader._leader_id)
        # One renewal per heartbeat, and none once the session has ended.
        self.assertEqual(timeline.waits, [state_stream._LEADER_HEARTBEAT_SECONDS] * 30)
        self.assertEqual(self.cache.touches, 29)
        self.assertEqual(ws_app.close_calls, 0)
        self.assertFalse(lost.is_set())

    def test_losing_the_key_mid_session_closes_the_session(self):
        self.assertTrue(self.leader._is_leader())
        start = self.clock.now

        def _evicted_and_taken() -> None:
            # The key is evicted at 70s and a polling worker takes it straight away.
            if self.clock.now == start + 70:
                self.cache.delete(state_stream._CACHE_LEADER_KEY)
                self.assertTrue(self.other._is_leader())

        timeline = _SessionTimeline(self.clock, duration=3600, every_second=_evicted_and_taken)
        with self.assertLogs("integrations_home_assistant", level="WARNING") as logs:
            ws_app, lost = self._renew(timeline)

        # The renewal at 80s finds the other worker's id, closes the session and stops renewing.
        self.assertEqual(len(timeline.waits), 4)
        self.assertEqual(ws_app.close_calls, 1)
        self.assertTrue(lost.is_set())
        self.assertEqual(self.cache.owner(), self.other._leader_id)
        self.assertIn("another worker holds the leader key", logs.output[0])

    def test_renewal_after_stop_leaves_the_released_key_alone(self):
        stop = self.leader._stop
        self.assertTrue(self.leader._is_leader())
        start = self.clock.now

        def _stopped() -> None:
            if self.clock.now == start + 30:
                self.leader.stop()

        timeline = _SessionTimeline(self.clock, duration=3600, every_second=_stopped)
        with self.assertNoLogs("integrations_home_assistant", level="WARNING"):
            ws_app, lost = self._renew(timeline, stop=stop)

        # The renewal at 20s ran. The one at 40s sees the stop and returns, without taking the released key
        # back or treating it as lost.
        self.assertEqual(len(timeline.waits), 2)
        self.assertEqual(self.cache.touches, 1)
        self.assertIsNone(self.cache.owner())
        self.assertEqual(ws_app.close_calls, 0)
        self.assertFalse(lost.is_set())
        self.assertTrue(self.other._is_leader())

    def test_renewal_never_overwrites_a_key_another_worker_took(self):
        self.assertTrue(self.leader._is_leader())

        def _expires_and_is_taken() -> None:
            # The race `_is_leader` documents: the key runs out right after our get, and another worker takes it.
            self.cache.on_get = None
            self.clock.now += state_stream._LEADER_TTL_SECONDS
            self.assertTrue(self.other._is_leader())

        self.cache.on_get = _expires_and_is_taken
        self.leader._is_leader()

        # The touch only moved the expiry, so the cache still names the other worker, and our next renewal
        # sees that and steps down.
        self.assertEqual(self.cache.owner(), self.other._leader_id)
        self.assertFalse(self.leader._is_leader())

    def test_renewal_retakes_a_key_that_ran_out_between_get_and_touch(self):
        self.assertTrue(self.leader._is_leader())

        def _expires() -> None:
            self.cache.on_get = None
            self.clock.now += state_stream._LEADER_TTL_SECONDS

        self.cache.on_get = _expires

        self.assertTrue(self.leader._is_leader())
        self.assertEqual(self.cache.owner(), self.leader._leader_id)

    def test_cache_error_during_a_session_keeps_the_session(self):
        # No cache is per-process behavior: every process leads, so a failing renewal mustn't end the session.
        timeline = _SessionTimeline(self.clock, duration=5 * state_stream._LEADER_TTL_SECONDS)
        with patch.object(state_stream, "cache", _FailingCache()):
            ws_app, lost = self._renew(timeline)

        self.assertEqual(len(timeline.waits), 15)
        self.assertEqual(ws_app.close_calls, 0)
        self.assertFalse(lost.is_set())


class _LiveSessionWebSocketApp:
    """
    Authenticates, then stays connected until something calls ``close()``, like a live HA session.

    ``after_auth`` runs once the session is authed. After the close, one more ``state_changed`` arrives,
    like a frame that was already on the wire.
    """

    after_auth = None
    instances: list[_LiveSessionWebSocketApp] = []

    def __init__(self, url, *, on_open, on_message, on_error, on_close):
        self._on_open = on_open
        self._on_message = on_message
        self._on_close = on_close
        self.closed = threading.Event()
        self.instances.append(self)

    def send(self, data: str) -> None:
        pass

    def close(self) -> None:
        self.closed.set()

    def run_forever(self, **_kwargs) -> bool:
        self._on_open(self)
        self._on_message(self, json.dumps({"type": "auth_required"}))
        self._on_message(self, json.dumps({"type": "auth_ok"}))
        if self.after_auth is not None:
            self.after_auth()
        if not self.closed.wait(timeout=5):
            raise AssertionError("the session was never closed")
        event = {"event_type": "state_changed", "data": {"entity_id": "binary_sensor.door"}}
        self._on_message(self, json.dumps({"type": "event", "event": event}))
        self._on_close(self, None, None)
        return False


class SessionLeaderRenewalTests(SimpleTestCase):
    """The renewal thread runs for exactly as long as a real ``_connect_and_listen`` session (#118)."""

    def setUp(self):
        self.cache = _FakeSharedCache(_FakeClock())
        self.stream = HomeAssistantStateStream()
        self.stream._settings = _SETTINGS
        self.other = HomeAssistantStateStream()
        self.renewal_threads: list[threading.Thread] = []
        real_renew = self.stream._renew_leadership_during_session

        def _tracking_renew(**kwargs) -> None:
            self.renewal_threads.append(threading.current_thread())
            real_renew(**kwargs)

        for patcher in (
            patch.object(state_stream, "cache", self.cache),
            # Real time, but short, so the renewal thread gets a few turns during the session.
            patch.object(state_stream, "_LEADER_HEARTBEAT_SECONDS", 0.01),
            patch.object(_LiveSessionWebSocketApp, "instances", []),
            patch("websocket.WebSocketApp", _LiveSessionWebSocketApp),
            patch.object(self.stream, "_renew_leadership_during_session", side_effect=_tracking_renew),
            patch.object(self.stream, "_handle_state_changed"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_renewal_runs_during_the_session_and_stops_when_it_ends(self):
        self.assertTrue(self.stream._is_leader())

        def _end_after_three_renewals() -> None:
            # HA closes the session once the renewal thread has renewed a few times.
            (ws_app,) = _LiveSessionWebSocketApp.instances

            def _watch() -> None:
                deadline = time.monotonic() + 5
                while self.cache.touches < 3 and time.monotonic() < deadline:
                    time.sleep(0.001)
                ws_app.close()

            threading.Thread(target=_watch, daemon=True).start()

        with patch.object(_LiveSessionWebSocketApp, "after_auth", staticmethod(_end_after_three_renewals)):
            authed_at = self.stream._connect_and_listen(
                ws_url="ws://ha:8123/api/websocket", token="token", stop=threading.Event()
            )

        self.assertIsNotNone(authed_at)
        self.assertGreaterEqual(self.cache.touches, 3)
        self.assertEqual(self.cache.owner(), self.stream._leader_id)
        (renewal_thread,) = self.renewal_threads
        # Gone by the time `_connect_and_listen` returns, so nothing renews the key once the session is over.
        self.assertFalse(renewal_thread.is_alive())
        self.assertIsNone(self.stream._ws_app)

    def test_losing_the_key_closes_the_session_and_backs_off_without_reconnecting(self):
        def _taken_by_other() -> None:
            # Another worker gets the key mid-session (it ran out, or the cache evicted it).
            self.cache.delete(state_stream._CACHE_LEADER_KEY)
            self.assertTrue(self.other._is_leader())

        stop = _RecordingStopEvent(max_waits=4)
        with (
            # The renewal thread checks the stop event on every turn too, so give it room before the guard trips.
            patch.object(_RecordingStopEvent, "_MAX_LOOP_CHECKS", 10_000),
            # Not the 1s leadership poll, so the backoff wait shows up on its own.
            patch.object(state_stream, "_RECONNECT_BACKOFF_INITIAL_SECONDS", 2.0),
            patch.object(_LiveSessionWebSocketApp, "after_auth", staticmethod(_taken_by_other)),
            self.assertLogs("integrations_home_assistant", level="WARNING") as logs,
        ):
            self.stream._run(stop)

        # One session, closed by the renewal, then the normal backoff, then polling for leadership instead of
        # reconnecting.
        (ws_app,) = _LiveSessionWebSocketApp.instances
        self.assertTrue(ws_app.closed.is_set())
        self.assertEqual(stop.waits, [2.0, 1.0, 1.0, 1.0])
        self.assertEqual(self.cache.owner(), self.other._leader_id)
        # The event that arrived after leadership was lost wasn't handled.
        self.stream._handle_state_changed.assert_not_called()
        (renewal_thread,) = self.renewal_threads
        self.assertFalse(renewal_thread.is_alive())
        self.assertTrue(any("another worker holds the leader key" in line for line in logs.output))


class LeaderReleaseTests(SimpleTestCase):
    """``stop()`` gives up the leader key, but only one this process still holds (#118)."""

    def setUp(self):
        self.cache = _FakeSharedCache(_FakeClock())
        patcher = patch.object(state_stream, "cache", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.stream = HomeAssistantStateStream()
        self.other = HomeAssistantStateStream()

    def test_stop_releases_a_key_this_process_holds(self):
        self.assertTrue(self.stream._is_leader())

        self.stream.stop()

        self.assertIsNone(self.cache.owner())
        # Another worker can take over straight away instead of waiting out the TTL.
        self.assertTrue(self.other._is_leader())

    def test_stop_leaves_another_workers_key_alone(self):
        self.assertTrue(self.other._is_leader())

        self.stream.stop()

        self.assertEqual(self.cache.owner(), self.other._leader_id)
        self.assertFalse(self.stream._is_leader())

    def test_shutdown_releases_the_key(self):
        self.assertTrue(self.stream._is_leader())

        with patch.object(state_stream, "_stream", self.stream):
            state_stream.shutdown()

        self.assertTrue(self.stream._stop.is_set())
        self.assertIsNone(self.cache.owner())

    def test_stop_with_a_failing_cache_still_stops(self):
        with patch.object(state_stream, "cache", _FailingCache()):
            self.stream.stop()

        self.assertTrue(self.stream._stop.is_set())

    def test_settings_restart_keeps_the_key_and_disabling_releases_it(self):
        # A restart keeps the key, so the new thread carries on as leader. The real `_is_leader` runs here.
        fake = FakeSessionStream(self)
        stream = fake.stream
        patcher = patch.object(HomeAssistantStateStream, "_is_leader", _real_is_leader)
        patcher.start()
        self.addCleanup(patcher.stop)

        with patch.object(state_stream, "_get_runtime_settings", return_value=_SETTINGS):
            stream.apply_runtime_settings_from_active_profile()
        fake.wait_for_session()
        self.assertEqual(self.cache.owner(), stream._leader_id)

        with patch.object(state_stream, "_get_runtime_settings", return_value=_NEW_SETTINGS):
            stream.apply_runtime_settings_from_active_profile()
        _, _, token, _ = fake.wait_for_current_session()
        self.assertEqual(token, "new-token")
        self.assertEqual(self.cache.owner(), stream._leader_id)
        # Never let go in between, where a polling worker could have taken it.
        self.assertEqual(self.cache.deletes, 0)

        with patch.object(state_stream, "_get_runtime_settings", return_value=_DISABLED):
            stream.apply_runtime_settings_from_active_profile()
        self.assertIsNone(self.cache.owner())


class LeaderCacheErrorTests(SimpleTestCase):
    def test_cache_error_falls_back_to_per_process_leadership(self):
        stream, stop = _make_stream(max_waits=1)
        with (
            patch.object(state_stream, "cache", _FailingCache()),
            patch.object(stream, "_connect_and_listen", return_value=None) as connect,
        ):
            self.assertTrue(stream._is_leader())
            stream._run(stop)

        # It connected as if it were the only process, rather than waiting for leadership.
        connect.assert_called_once()
        self.assertEqual(stop.waits, [1.0])
