"""
One runtime process per database (ADR-0112, #162).

`should_start_runtimes()` asks :func:`acquire_for_process` before a process starts the runtimes (MQTT, Z-Wave JS,
the HA state stream, control panels, the scheduler). On Postgres that takes a session advisory lock on a dedicated
connection, so only one process per database runs them. A process that doesn't get it is a standby. It serves
HTTP, starts no runtimes and logs who has the lock.

The answer is worked out once per process and sticks. A heartbeat thread checks the connection every 30s, takes
the lock again after a reconnect, and exits the process if someone else got it in between, so supervisord starts
it again as a standby.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from django.conf import settings
from django.db import connections

logger = logging.getLogger(__name__)

# `pg_try_advisory_lock(int4, int4)`. Postgres keeps the two-int key space apart from the single bigint one that
# `lock_sync:` (locks/use_cases/lock_config_sync.py) uses, so the two can't collide.
LOCK_NAMESPACE = 0x4C505254  # "LPRT"
LOCK_KEY = 1

HEARTBEAT_SECONDS = 30.0
HOLDER_LOG_SECONDS = 300.0
RECONNECT_RETRY_SECONDS = 5.0
# How long a session of this process's own that Postgres hasn't dropped yet gets to go away.
STALE_SESSION_WAIT_SECONDS = 60.0
STALE_SESSION_RETRY_SECONDS = 0.5
STARTUP_ATTEMPTS = 5
STARTUP_RETRY_SECONDS = 2.0
CONNECT_TIMEOUT_SECONDS = 10

# Server side, so Postgres drops the session (and the lock with it) about 25s after the holder's host goes away.
SERVER_KEEPALIVES = {"tcp_keepalives_idle": 10, "tcp_keepalives_interval": 5, "tcp_keepalives_count": 3}
# Client side, so this process notices a dead server instead of waiting on the socket.
_CLIENT_KEEPALIVES = {"keepalives": 1, "keepalives_idle": 10, "keepalives_interval": 5, "keepalives_count": 3}
# Gives up on a query whose packets go unacknowledged this long (ms), ie a heartbeat stuck in a network partition.
_TCP_USER_TIMEOUT_MS = 30_000

ACTIVE = "active"
HELD_ELSEWHERE = "held_elsewhere"
DISABLED = "disabled"

_NOT_CHECKED = "runtimes aren't started in this process"

_APP_NAME_PREFIX = "latchpoint-runtime"
# application_name is cut to 63 bytes by Postgres. The hostname gets cut instead, so the pid always fits.
_MAX_HOST_CHARS = 63 - len(_APP_NAME_PREFIX) - len("::") - 7

_TRY_LOCK_SQL = "SELECT pg_try_advisory_lock(%s, %s)"
# objsubid 2 is the two-int form.
_HOLDER_SQL = """
SELECT a.pid, a.application_name, host(a.client_addr)
FROM pg_locks l
JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.locktype = 'advisory'
  AND l.granted
  AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND l.classid = %s
  AND l.objid = %s
  AND l.objsubid = 2
LIMIT 1
"""

_T = TypeVar("_T")


class RuntimeLockUnavailable(RuntimeError):
    """The database couldn't be reached to check the runtime lock when the process started."""


def default_application_name() -> str:
    """`latchpoint-runtime:<hostname>:<pid>`, what the holder query shows for this process."""
    host = (socket.gethostname() or "unknown")[:_MAX_HOST_CHARS]
    return f"{_APP_NAME_PREFIX}:{host}:{os.getpid()}"


def describe_holder(holder: dict[str, Any] | None) -> str:
    """One line about the session that holds the lock, for the logs."""
    if not holder:
        return "nobody"
    name = holder.get("application_name") or "(no application_name)"
    client = holder.get("client_addr") or "a local socket"
    return f"{name} (backend pid {holder.get('pid')}, from {client})"


class RuntimeLock:
    """
    The runtime lock for one process.

    The module keeps the process's own instance (see :func:`acquire_for_process`). Tests make their own, with an
    `application_name` per instance so 2 of them in one process don't look like the same process.
    """

    def __init__(
        self,
        *,
        alias: str = "default",
        application_name: str | None = None,
        start_heartbeat: bool = True,
    ) -> None:
        self._alias = alias
        self._fixed_application_name = application_name
        self._start_heartbeat = start_heartbeat
        self._mutex = threading.RLock()
        self._decided = False
        self._result = False
        self._state = DISABLED
        self._reason = _NOT_CHECKED
        self._holder: dict[str, Any] | None = None
        self._conn: Any = None
        self._backend_pid: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fork_hook_registered = False
        # A forked child keeps the connection it inherited here and never touches it (see _after_fork_in_child).
        self._inherited_connections: list[Any] = []
        self._last_holder_log: float | None = None

    @property
    def application_name(self) -> str:
        return self._fixed_application_name or default_application_name()

    # -- deciding ---------------------------------------------------------------------------------------------

    def acquire_for_process(self) -> bool:
        """
        Return True if this process may start the runtimes, working it out on the first call only.

        True when it took the lock or the lock is off (`RUNTIME_LOCK=off`, or not Postgres). False when another
        process holds it. Raises :class:`RuntimeLockUnavailable` if the database can't be reached.
        """
        with self._mutex:
            if self._decided:
                return self._result
            self._result = _call_outside_event_loop(self._decide)
            self._decided = True
            return self._result

    def _decide(self) -> bool:
        mode = _mode()
        if mode == "off":
            self._set_disabled("RUNTIME_LOCK=off")
            logger.info("Runtime lock is off (RUNTIME_LOCK=off), so this process starts the runtimes without it")
            return True
        vendor = connections[self._alias].vendor
        if vendor != "postgresql":
            self._set_disabled(f"the database is {vendor}, not postgresql")
            logger.info("Runtime lock skipped on %s, so this process starts the runtimes without it", vendor)
            return True

        acquired, holder = self._acquire_at_startup()
        if acquired:
            self._set_active()
            logger.info(
                "Runtime lock taken by %s (backend pid %s), so this process starts the runtimes",
                self.application_name,
                self._backend_pid,
            )
        else:
            self._set_held_elsewhere(holder)
            self._last_holder_log = time.monotonic()
            self._log_standby(holder)
        self._start_heartbeat_thread()
        return acquired

    def _acquire_at_startup(self) -> tuple[bool, dict[str, Any] | None]:
        last_exc: Exception | None = None
        for attempt in range(1, STARTUP_ATTEMPTS + 1):
            try:
                self._open_connection()
                return self._take_lock()
            except Exception as exc:
                last_exc = exc
                self._drop_connection()
                if attempt < STARTUP_ATTEMPTS:
                    logger.warning(
                        "Runtime lock: can't reach the database (%s), trying again in %ss (%s/%s)",
                        exc,
                        STARTUP_RETRY_SECONDS,
                        attempt,
                        STARTUP_ATTEMPTS,
                    )
                    time.sleep(STARTUP_RETRY_SECONDS)
        raise RuntimeLockUnavailable(
            f"Couldn't reach the database to check the runtime lock after {STARTUP_ATTEMPTS} tries (ADR-0112)"
        ) from last_exc

    # -- the connection and the lock --------------------------------------------------------------------------

    def _open_connection(self) -> None:
        """Open the dedicated connection, never Django's thread-local one, so nothing else closes it."""
        wrapper = connections[self._alias]
        params = wrapper.get_connection_params()
        params["application_name"] = self.application_name
        params.setdefault("connect_timeout", CONNECT_TIMEOUT_SECONDS)
        for key, value in _CLIENT_KEEPALIVES.items():
            params.setdefault(key, value)
        if _libpq_supports_tcp_user_timeout():
            params.setdefault("tcp_user_timeout", _TCP_USER_TIMEOUT_MS)
        server_options = " ".join(f"-c {key}={value}" for key, value in SERVER_KEEPALIVES.items())
        existing = str(params.get("options") or "").strip()
        params["options"] = f"{existing} {server_options}" if existing else server_options

        conn = wrapper.get_new_connection(params)
        # Autocommit, so the heartbeat never leaves the session idle in a transaction, which
        # idle_in_transaction_session_timeout would end, lock and all.
        conn.autocommit = True
        self._conn = conn
        self._backend_pid = int(self._fetch_one("SELECT pg_backend_pid()")[0])
        self._register_fork_hook()

    def _take_lock(self) -> tuple[bool, dict[str, Any] | None]:
        """
        Try the lock on the open connection. Returns whether it was taken, and the holder when it wasn't.

        A holder with this process's own application_name is a session of ours Postgres hasn't dropped yet (ie
        the connection the heartbeat just lost, or the same pid before a container restart), so it's terminated
        and the lock tried again, for up to STALE_SESSION_WAIT_SECONDS.
        """
        deadline = time.monotonic() + STALE_SESSION_WAIT_SECONDS
        while True:
            if bool(self._fetch_one(_TRY_LOCK_SQL, [LOCK_NAMESPACE, LOCK_KEY])[0]):
                return True, None
            holder = self._query_holder()
            ours = holder is None or holder.get("application_name") == self.application_name
            if not ours or time.monotonic() >= deadline:
                return False, holder
            if holder is not None:
                logger.warning(
                    "Runtime lock: held by an old session of this process (backend pid %s) that Postgres hasn't "
                    "dropped yet, terminating it",
                    holder.get("pid"),
                )
                self._fetch_one("SELECT pg_terminate_backend(%s)", [holder.get("pid")])
            time.sleep(STALE_SESSION_RETRY_SECONDS)

    def _query_holder(self) -> dict[str, Any] | None:
        row = self._fetch_one(_HOLDER_SQL, [LOCK_NAMESPACE, LOCK_KEY])
        if not row:
            return None
        return {"pid": row[0], "application_name": row[1] or None, "client_addr": row[2] or None}

    def _fetch_one(self, sql: str, params: list[Any] | None = None) -> Any:
        with self._conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def _ping(self) -> None:
        self._fetch_one("SELECT 1")

    def _drop_connection(self) -> None:
        conn, self._conn = self._conn, None
        self._backend_pid = None
        if conn is not None:
            self._close_quietly(conn)

    @staticmethod
    def _close_quietly(conn: Any) -> None:
        try:
            conn.close()
        except Exception:
            logger.debug("Runtime lock: closing the old connection failed", exc_info=True)

    # -- heartbeat --------------------------------------------------------------------------------------------

    def _start_heartbeat_thread(self) -> None:
        if not self._start_heartbeat or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._heartbeat_loop, name="runtime-lock-heartbeat", daemon=True)
        self._thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                self.heartbeat_once()
            except Exception:
                logger.exception("Runtime lock heartbeat failed")

    def heartbeat_once(self) -> None:
        """One heartbeat tick. The thread calls this every HEARTBEAT_SECONDS, tests call it directly."""
        if self._state == ACTIVE:
            self._check_active()
        elif self._state == HELD_ELSEWHERE:
            self._check_standby()

    def _check_active(self) -> None:
        try:
            self._ping()
            return
        except Exception as exc:
            logger.warning("Runtime lock: lost the database connection (%s), reconnecting to take the lock again", exc)
        # The lock went with the session. Closing the old connection makes sure of that, if it's still there.
        self._drop_connection()

        attempt = 0
        while not self._stop.is_set():
            attempt += 1
            try:
                self._open_connection()
                acquired, holder = self._take_lock()
            except Exception as exc:
                self._drop_connection()
                # The first failure and then about once a minute, so a long outage doesn't flood the log.
                level = logging.WARNING if attempt % 12 == 1 else logging.DEBUG
                logger.log(
                    level, "Runtime lock: can't reconnect yet (%s), retrying every %ss", exc, RECONNECT_RETRY_SECONDS
                )
                self._stop.wait(RECONNECT_RETRY_SECONDS)
                continue
            if acquired:
                logger.warning(
                    "Runtime lock: took the lock again after reconnecting (backend pid %s)", self._backend_pid
                )
                return
            with self._mutex:
                self._set_held_elsewhere(holder)
            logger.critical(
                "Runtime lock: lost the lock while the connection was down and %s has it now. This process "
                "still runs the runtimes, so it exits to restart as a standby (ADR-0112)",
                describe_holder(holder),
            )
            _exit_process()
            return

    def _check_standby(self) -> None:
        now = time.monotonic()
        if self._last_holder_log is not None and now - self._last_holder_log < HOLDER_LOG_SECONDS:
            return
        self._last_holder_log = now
        try:
            if self._conn is None:
                self._open_connection()
            holder = self._query_holder()
        except Exception as exc:
            self._drop_connection()
            logger.error(
                "Runtime lock: this process is a standby and starts no runtimes, and checking who holds the lock "
                "failed (%s). Run one process per database (ADR-0112)",
                exc,
            )
            return
        with self._mutex:
            self._holder = holder
        self._log_standby(holder)

    def _log_standby(self, holder: dict[str, Any] | None) -> None:
        if holder is None:
            logger.error(
                "Runtime lock: the lock is free now, but this process started as a standby and runs no runtimes "
                "(MQTT, Z-Wave JS, Home Assistant, control panels, scheduler). Restart it to take the lock (ADR-0112)"
            )
            return
        logger.error(
            "Runtime lock: held by %s, so this process is a standby and starts no runtimes (MQTT, Z-Wave JS, "
            "Home Assistant, control panels, scheduler). It still serves HTTP. Run one process per database "
            "(ADR-0112)",
            describe_holder(holder),
        )

    # -- forks ------------------------------------------------------------------------------------------------

    def _register_fork_hook(self) -> None:
        if self._fork_hook_registered or not hasattr(os, "register_at_fork"):
            return
        os.register_at_fork(after_in_child=self._after_fork_in_child)
        self._fork_hook_registered = True

    def _after_fork_in_child(self) -> None:
        """
        Runs in a child forked from this process (ie gunicorn `--preload`).

        The child shares the parent's socket to Postgres, so it must never use or close the inherited connection.
        Closing it sends Postgres a terminate on that socket, which ends the parent's session and frees the
        parent's lock. So it's moved out of `_conn`, where :meth:`close` and the heartbeat would find it, and kept
        referenced rather than left to the garbage collector (psycopg2 skips the close on a dealloc in another
        process, but nothing here should depend on that). The child doesn't hold the lock, and the runtime
        threads didn't survive the fork.
        """
        conn = self._conn
        if conn is None:
            return
        self._inherited_connections.append(conn)
        self._conn = None
        # Whatever held these in the parent's other threads is gone in the child.
        self._mutex = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        was_active = self._state == ACTIVE
        if was_active:
            self._holder = {
                "pid": self._backend_pid,
                "application_name": self.application_name,
                "client_addr": None,
            }
            self._state = HELD_ELSEWHERE
        self._result = False
        self._decided = True
        logger.critical(
            "Runtime lock: process %s was forked from %s after Django started. The child doesn't hold the runtime "
            "lock and the runtime threads didn't survive the fork, so it runs no runtimes. Don't fork after "
            "startup, ie no gunicorn --preload (ADR-0112)",
            os.getpid(),
            os.getppid(),
        )

    # -- status -----------------------------------------------------------------------------------------------

    def _set_active(self) -> None:
        self._state = ACTIVE
        self._holder = None
        self._reason = ""

    def _set_held_elsewhere(self, holder: dict[str, Any] | None) -> None:
        self._state = HELD_ELSEWHERE
        self._holder = holder
        self._reason = ""

    def _set_disabled(self, reason: str) -> None:
        self._state = DISABLED
        self._holder = None
        self._reason = reason

    def get_status(self) -> dict[str, Any]:
        """`active`, `held_elsewhere` with the holder, or `disabled` with the reason."""
        with self._mutex:
            if self._state == ACTIVE:
                return {"state": ACTIVE, "application_name": self.application_name}
            if self._state == HELD_ELSEWHERE:
                return {"state": HELD_ELSEWHERE, "holder": dict(self._holder) if self._holder else None}
            return {"state": DISABLED, "reason": self._reason}

    def is_held_elsewhere(self) -> bool:
        return self._state == HELD_ELSEWHERE

    def close(self) -> None:
        """Stop the heartbeat and close the connection, which frees the lock. For tests."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5)
        self._drop_connection()


def _mode() -> str:
    raw = str(getattr(settings, "RUNTIME_LOCK", "auto") or "").strip().lower()
    if raw in ("", "auto"):
        return "auto"
    if raw == "off":
        return "off"
    logger.warning("RUNTIME_LOCK=%r isn't auto or off, so it's treated as auto", raw)
    return "auto"


def _libpq_supports_tcp_user_timeout() -> bool:
    try:
        from psycopg2.extensions import libpq_version
    except ImportError:
        return False
    return libpq_version() >= 120000


def _call_outside_event_loop(fn: Callable[[], _T]) -> _T:
    """
    Call `fn` here, or in a short-lived thread if this thread runs an event loop.

    uvicorn imports the app (and so runs `ready()`) inside its event loop, where Django refuses to open a
    connection (`SynchronousOnlyOperation`). daphne and runserver don't.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn()

    outcome: dict[str, Any] = {}

    def _run() -> None:
        try:
            outcome["result"] = fn()
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=_run, name="runtime-lock-startup")
    thread.start()
    thread.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def _exit_process() -> None:
    """Exit now, so supervisord restarts the process. `os._exit` skips atexit and buffered output, so flush first."""
    for handler in logging.getLogger().handlers:
        with contextlib.suppress(Exception):
            handler.flush()
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    os._exit(1)


_process_lock = RuntimeLock()


def acquire_for_process() -> bool:
    """Whether this process may start the runtimes. See :meth:`RuntimeLock.acquire_for_process`."""
    return _process_lock.acquire_for_process()


def get_status() -> dict[str, Any]:
    """This process's runtime lock state, for the scheduler and system status payloads."""
    return _process_lock.get_status()


def is_held_elsewhere() -> bool:
    """True in a standby, ie another process holds the runtime lock and runs the runtimes."""
    return _process_lock.is_held_elsewhere()


def reset_for_tests() -> None:
    """Close this process's lock and start over, so a test can exercise it."""
    global _process_lock
    _process_lock.close()
    _process_lock = RuntimeLock()
