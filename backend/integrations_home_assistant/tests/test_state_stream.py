"""Reconnect backoff for the HA state stream (#108, #114).

websocket-client's ``run_forever`` returns instead of raising when the connection is refused,
so ``_run`` has to back off after every session, not only after an exception. A session that
reaches ``auth_ok`` only resets the backoff once it has stayed up for a while, so a connection
HA drops right after auth keeps backing off too.
"""

from __future__ import annotations

import json
import threading
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations_home_assistant import state_stream
from integrations_home_assistant.state_stream import HomeAssistantStateStream, _RuntimeSettings

_SETTINGS = _RuntimeSettings(enabled=True, base_url="http://ha:8123", token="token")


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


class _FakeClock:
    """Replaces ``time.monotonic`` so session lengths don't need real time to pass."""

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
    stop = _RecordingStopEvent(max_waits=max_waits)
    stream._stop = stop
    return stream, stop


@patch.object(HomeAssistantStateStream, "_is_leader", return_value=True)
class StateStreamBackoffTests(SimpleTestCase):
    def test_return_without_auth_ok_backs_off_and_grows_to_cap(self, _leader):
        stream, stop = _make_stream(max_waits=7)
        with patch.object(stream, "_connect_and_listen", return_value=None) as connect:
            stream._run()

        self.assertEqual(stop.waits, [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0])
        self.assertEqual(connect.call_count, 7)

    def test_connection_that_reached_auth_ok_resets_backoff(self, _leader):
        stream, stop = _make_stream(max_waits=5)
        clock = _FakeClock()
        sessions = _sessions(clock, [None, None, None, state_stream._RECONNECT_HEALTHY_SESSION_SECONDS])
        with (
            patch.object(state_stream.time, "monotonic", clock),
            patch.object(stream, "_connect_and_listen", side_effect=sessions),
        ):
            stream._run()

        self.assertEqual(stop.waits, [1.0, 2.0, 4.0, 1.0, 1.0])

    def test_authed_session_shorter_than_threshold_keeps_backing_off_to_cap(self, _leader):
        # The #114 flap: HA sends auth_ok and drops the connection 0.2s later, every time.
        stream, stop = _make_stream(max_waits=7)
        clock = _FakeClock()
        with (
            patch.object(state_stream.time, "monotonic", clock),
            patch.object(stream, "_connect_and_listen", side_effect=_sessions(clock, [0.2] * 7)) as connect,
        ):
            stream._run()

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
                    patch.object(state_stream.time, "monotonic", clock),
                    patch.object(stream, "_connect_and_listen", side_effect=sessions),
                ):
                    stream._run()

                # Just under the threshold counts as a failed attempt, at or over it resets.
                self.assertEqual(stop.waits, [1.0, 2.0, 4.0, 8.0, 1.0, 1.0])

    def test_healthy_session_threshold_is_patchable(self, _leader):
        stream, stop = _make_stream(max_waits=4)
        clock = _FakeClock()
        with (
            patch.object(state_stream, "_RECONNECT_HEALTHY_SESSION_SECONDS", 0.5),
            patch.object(state_stream.time, "monotonic", clock),
            patch.object(stream, "_connect_and_listen", side_effect=_sessions(clock, [None, None, 0.25, 0.5])),
        ):
            stream._run()

        self.assertEqual(stop.waits, [1.0, 2.0, 4.0, 1.0])

    def test_exception_still_backs_off(self, _leader):
        stream, stop = _make_stream(max_waits=3)
        with (
            patch.object(stream, "_connect_and_listen", side_effect=RuntimeError("boom")),
            # The backoff must go through the stop event, never a blocking sleep.
            patch.object(state_stream.time, "sleep", side_effect=AssertionError("blocking sleep in backoff")),
        ):
            stream._run()

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
            thread = threading.Thread(target=stream._run, daemon=True)
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
            stream._run()

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
            thread = threading.Thread(target=stream._run, daemon=True)
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
            return stream._connect_and_listen(ws_url="ws://ha:8123/api/websocket", token="token")

    def test_refused_connection_returns_none(self):
        self.assertIsNone(self._run_session([]))

    def test_auth_invalid_returns_none(self):
        self.assertIsNone(self._run_session([{"type": "auth_required"}, {"type": "auth_invalid", "message": "bad"}]))

    def test_auth_ok_returns_monotonic_time_of_auth_ok(self):
        with patch.object(state_stream.time, "monotonic", return_value=123.0):
            authed_at = self._run_session([{"type": "auth_required"}, {"type": "auth_ok"}])
        self.assertEqual(authed_at, 123.0)
