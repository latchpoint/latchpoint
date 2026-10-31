"""Locks runtime: count door code uses from Z-Wave JS keypad unlocks (issue #145, ADR-0114).

Registers a listener on the Z-Wave JS event bridge like ``control_panels.runtime``.
The listener runs on the bridge's one ``zwavejs-events`` thread, which also
carries Ring keypad codes, so it only parses the event, logs CC 113 events and
hands keypad unlocks to :data:`keypad_use_worker`. The counting takes the code
row with ``select_for_update``, which can wait on a push or lock sync holding
it, so it runs on that worker's own thread and never holds up the events
thread (ADR-0100). Only the process with the runtime lock starts this (ADR-0112).
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any

from locks.keypad_events import (
    KeypadUnlock,
    is_notification_cc_event,
    keypad_event_log_fields,
    parse_keypad_unlock,
)

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_initialized = False

# Keypad unlocks waiting to be counted. A lock reports one per unlock, so this
# only fills up when the DB is stuck, and then dropping one is logged.
_QUEUE_SIZE = 256


def _close_old_connections() -> None:
    """Drop this thread's DB connection when it's broken or past its age.

    Never on the main thread, where a test's transaction would lose its connection.
    """
    if threading.current_thread() is threading.main_thread():
        return
    try:
        from django.db import close_old_connections

        close_old_connections()
    except Exception:
        return


def _home_id() -> int | None:
    try:
        from alarm.gateways.zwavejs import default_zwavejs_gateway

        return default_zwavejs_gateway.get_home_id()
    except Exception:
        return None


class KeypadUseWorker:
    """One background thread that counts keypad unlocks, in the order they came in."""

    def __init__(self, *, maxsize: int = _QUEUE_SIZE) -> None:
        self._queue: queue.Queue[KeypadUnlock] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the thread if it isn't running (idempotent)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="locks-keypad-uses", daemon=True)
            self._thread.start()

    def submit(self, unlock: KeypadUnlock) -> bool:
        """Queue ``unlock`` without blocking. ``False`` (and a warning) when the queue is full."""
        try:
            self._queue.put_nowait(unlock)
        except queue.Full:
            logger.warning(
                "Door code use: queue full, dropped keypad unlock node=%s slot=%s", unlock.node_id, unlock.slot
            )
            return False
        return True

    def join(self) -> None:
        """Wait until everything queued so far has been handled (for tests)."""
        self._queue.join()

    def _run(self) -> None:
        while True:
            unlock = self._queue.get()
            try:
                self.handle(unlock)
            except Exception:
                logger.exception(
                    "Door code use: failed counting keypad unlock node=%s slot=%s", unlock.node_id, unlock.slot
                )
            finally:
                self._queue.task_done()

    def handle(self, unlock: KeypadUnlock) -> None:
        """Count one keypad unlock on this thread's own DB connection."""
        from locks.use_cases.code_usage import handle_keypad_unlock

        _close_old_connections()
        try:
            handle_keypad_unlock(unlock, home_id=_home_id())
        finally:
            _close_old_connections()


keypad_use_worker = KeypadUseWorker()


def make_event_listener(*, worker: KeypadUseWorker):
    """The bridge listener: log CC 113 events, queue keypad unlocks on ``worker``.

    The log line only has the allowlisted fields (:func:`keypad_event_log_fields`),
    never the payload. Each unlock is stamped with when it came in.
    """

    def _on_event(msg: dict[str, Any]) -> None:
        try:
            if not is_notification_cc_event(msg):
                return
            from django.utils import timezone as django_timezone

            unlock = parse_keypad_unlock(msg, received_at=django_timezone.now())
            logger.info("zwavejs keypad event %s", keypad_event_log_fields(msg))
            if unlock is not None:
                worker.submit(unlock)
        except Exception:
            logger.exception("Locks: failed handling zwavejs event")

    return _on_event


def initialize() -> None:
    """Register the keypad unlock listener and start the worker (idempotent)."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

    try:
        from alarm.gateways.zwavejs import default_zwavejs_gateway

        manager = getattr(default_zwavejs_gateway, "manager", None)
        register = getattr(manager, "register_event_listener", None)
    except Exception:
        logger.debug("Z-Wave JS gateway not available; locks runtime not initialized.")
        return
    if not callable(register):
        return

    keypad_use_worker.start()
    register(make_event_listener(worker=keypad_use_worker))
    logger.info("Locks: registered Z-Wave JS keypad unlock listener + keypad-use worker.")
