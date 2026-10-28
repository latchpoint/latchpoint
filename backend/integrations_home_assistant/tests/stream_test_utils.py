"""Shared fakes for tests that run a real ``HomeAssistantStateStream`` without talking to Home Assistant."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.apps import apps

from alarm.signals import alarm_state_change_committed, settings_profile_changed
from integrations_home_assistant import apps as ha_apps
from integrations_home_assistant import state_stream
from integrations_home_assistant.connection import clear_cached_connection
from integrations_home_assistant.state_stream import HomeAssistantStateStream


class FakeSessionStream:
    """
    A real stream, swapped in as the module's ``_stream``, whose sessions never touch the network.

    Each session records itself and returns right away, so its thread parks in the backoff wait until it's
    stopped. ``wait_for_session()`` waits for the next one to start.
    """

    def __init__(self, testcase):
        self.stream = HomeAssistantStateStream()
        self.sessions: list[tuple[threading.Thread, str, str, threading.Event]] = []
        # Every thread this stream started, so a thread leaked by another test can't throw the checks off.
        self.threads: list[threading.Thread] = []
        self._started = threading.Semaphore(0)
        self._seen = 0
        start = self.stream.start

        def _tracking_start() -> None:
            start()
            if self.stream._thread is not None and self.stream._thread not in self.threads:
                self.threads.append(self.stream._thread)

        for patcher in (
            patch.object(HomeAssistantStateStream, "_is_leader", return_value=True),
            patch.object(state_stream, "_RECONNECT_BACKOFF_INITIAL_SECONDS", 60.0),
            patch.object(state_stream, "_stream", self.stream),
            patch.object(self.stream, "_connect_and_listen", side_effect=self._connect),
            patch.object(self.stream, "start", side_effect=_tracking_start),
        ):
            patcher.start()
            testcase.addCleanup(patcher.stop)
        testcase.addCleanup(self._stop_all)

    def _connect(self, *, ws_url: str, token: str, stop: threading.Event) -> float | None:
        self.sessions.append((threading.current_thread(), ws_url, token, stop))
        self._started.release()
        return None

    def _stop_all(self) -> None:
        self.stream.wait_for_background_apply(timeout=5)
        self.stream.stop()
        for thread in self.threads:
            thread.join(timeout=5)

    def wait_for_session(self) -> tuple[threading.Thread, str, str, threading.Event]:
        """Wait for the next session this test hasn't seen yet and return it."""
        if not self._started.acquire(timeout=5):
            raise AssertionError("the stream didn't start a session")
        self._seen += 1
        return self.sessions[self._seen - 1]

    def wait_for_current_session(self) -> tuple[threading.Thread, str, str, threading.Event]:
        """
        Wait for a session on the stream's current thread and return it.

        For when an earlier thread may or may not have run a session before it was stopped, since a thread
        reads the settings when it starts its loop.
        """
        while True:
            for session in self.sessions:
                if session[0] is self.stream._thread:
                    return session
            if not self._started.acquire(timeout=5):
                raise AssertionError("the stream's current thread didn't start a session")


class RecordingLock:
    """
    A lock that records which threads have tried to take it, so a test can wait until one is queued on it.

    ``holder`` is the thread holding it right now, or None.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._attempts: list[threading.Thread] = []
        self._changed = threading.Condition()
        self.holder: threading.Thread | None = None

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        with self._changed:
            self._attempts.append(threading.current_thread())
            self._changed.notify_all()
        acquired = self._lock.acquire(blocking, timeout)
        if acquired:
            self.holder = threading.current_thread()
        return acquired

    def release(self) -> None:
        self.holder = None
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()

    def locked(self) -> bool:
        return self._lock.locked()

    def wait_until_tried(self, thread: threading.Thread, timeout: float = 5) -> None:
        """Return once `thread` has tried to take the lock, or has finished without trying."""
        with self._changed:
            if not self._changed.wait_for(lambda: thread in self._attempts or not thread.is_alive(), timeout):
                raise AssertionError(f"{thread.name} never tried to take the lock")


def run_app_ready(testcase, argv: list[str] | None = None) -> MagicMock:
    """
    Run the HA app's ``ready()`` the way a server process does.

    ``ready()`` skips itself outside the server, ie under ``manage.py test``, so this gives the ``apps``
    module a ``sys`` whose argv looks like daphne, or ``argv`` if given (ie a management command's). Only
    that module's ``sys`` name is swapped, the real ``sys.argv`` other threads read (ie
    ``_home_assistant_allowed_in_tests()``) is left alone. The signal handlers it connects are disconnected
    again on cleanup.

    The module's ``atexit`` is swapped too, so the test process doesn't pick up exit hooks. Returns that
    stand-in so a test can check what ``ready()`` registered.
    """
    config = apps.get_app_config("integrations_home_assistant")
    testcase.addCleanup(clear_cached_connection)
    testcase.addCleanup(_disconnect_app_handlers)
    fake_atexit = MagicMock()
    if argv is None:
        argv = ["daphne", "config.asgi:application"]
    with (
        patch.object(ha_apps, "sys", SimpleNamespace(argv=argv)),
        patch.object(ha_apps, "atexit", fake_atexit),
        patch("integrations_home_assistant.mqtt_alarm_entity.initialize_home_assistant_mqtt_alarm_entity_integration"),
    ):
        config.ready()
    return fake_atexit


def _disconnect_app_handlers() -> None:
    settings_profile_changed.disconnect(dispatch_uid="ha_connection_profile_changed")
    settings_profile_changed.disconnect(dispatch_uid="ha_mqtt_alarm_entity_profile_changed")
    alarm_state_change_committed.disconnect(dispatch_uid="ha_mqtt_alarm_entity_state")
