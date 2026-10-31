"""
One runtime process per database (ADR-0112, #162).

`should_start_runtimes()` asks :func:`acquire_for_process` before a process starts the runtimes (MQTT, Z-Wave JS,
the HA state stream, control panels, the scheduler). On Postgres that takes a session advisory lock on a dedicated
connection, so only one process per database runs them. A process that doesn't get it is a standby. It serves
HTTP, starts no runtimes and logs who has the lock.

The answer is worked out once per process and sticks. A heartbeat thread checks the connection every 30s, takes
the lock again after a reconnect, and exits the process if someone else got it in between, so supervisord starts
it again as a standby. A standby checks too, and exits once the lock is free so it comes back and takes it.

A session is told apart by its backend pid and start time, never by its application_name, so the only session
this ever terminates is the exact one the heartbeat just lost.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
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
# How long the session the heartbeat lost, if Postgres hasn't dropped it yet, gets to go away.
STALE_SESSION_WAIT_SECONDS = 60.0
STALE_SESSION_RETRY_SECONDS = 0.5
# At startup, how long a holder from this same host (ie this container before supervisord restarted daphne, whose
# session Postgres hasn't dropped yet) gets to go away before this process settles for being a standby. Past the
# ~25s the server keepalives take to drop a dead session.
PREVIOUS_RUN_WAIT_SECONDS = 35.0
PREVIOUS_RUN_POLL_SECONDS = 1.0
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

# The scheduler's old leader lock (#162). The runtime lock covers the scheduler now.
_DEPRECATED_SETTINGS = ("SCHEDULER_LEADER_LOCK_ENABLED", "SCHEDULER_LEADER_LOCK_ID")

_APP_NAME_PREFIX = "latchpoint-runtime"
_BOOT_TOKEN_HEX_CHARS = 6
# application_name is cut to 63 bytes by Postgres. The hostname gets cut instead, so the pid and token always fit.
_MAX_HOST_CHARS = 63 - len(_APP_NAME_PREFIX) - len(":::") - 7 - _BOOT_TOKEN_HEX_CHARS
# One per process (a forked child gets its own), so 2 processes never share a name, even 2 containers with the
# same hostname and pid.
_boot_tokens: dict[int, str] = {}

_TRY_LOCK_SQL = "SELECT pg_try_advisory_lock(%s, %s)"
# Which session this connection is. The pid alone could in theory be reused by a later backend, the start time
# with it can't.
_OWN_SESSION_SQL = "SELECT pid, backend_start::text FROM pg_stat_activity WHERE pid = pg_backend_pid()"
# objsubid 2 is the two-int form.
_HOLDER_SQL = """
SELECT a.pid, a.application_name, host(a.client_addr), a.backend_start::text
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
    """
    `latchpoint-runtime:<hostname>:<pid>:<boot token>`, what the holder query shows for this process.

    The hostname is cut down to printable ASCII, which is all Postgres keeps in an application_name, so the name
    Postgres reports is the one built here. It's for people reading the logs and for spotting a holder from this
    same host, never for telling sessions apart.
    """
    raw = socket.gethostname() or "unknown"
    host = "".join(c if 32 <= ord(c) < 127 and c != ":" else "?" for c in raw)[:_MAX_HOST_CHARS]
    return f"{_APP_NAME_PREFIX}:{host}:{os.getpid()}:{_boot_token()}"


def _boot_token() -> str:
    pid = os.getpid()
    token = _boot_tokens.get(pid)
    if token is None:
        token = _boot_tokens[pid] = secrets.token_hex(_BOOT_TOKEN_HEX_CHARS // 2)
    return token


def _host_prefix(application_name: str | None) -> str | None:
    """`latchpoint-runtime:<hostname>:` for one of our names, None for anything else."""
    parts = (application_name or "").split(":")
    if len(parts) < 3 or parts[0] != _APP_NAME_PREFIX or not parts[1]:
        return None
    return f"{parts[0]}:{parts[1]}:"


def _is_session(holder: dict[str, Any], session: tuple[int, str | None] | None) -> bool:
    """Whether `holder` is exactly `session`, matched on backend pid and start time."""
    return session is not None and holder.get("pid") == session[0] and holder.get("backend_start") == session[1]


def _public_holder(holder: dict[str, Any] | None) -> dict[str, Any] | None:
    """The holder as the status payloads show it."""
    if not holder:
        return None
    return {key: holder.get(key) for key in ("pid", "application_name", "client_addr")}


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
        # (backend pid, backend_start) of the session on `_conn`.
        self._session: tuple[int, str | None] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fork_hook_registered = False
        # A forked child keeps the connection it inherited here and never touches it (see _after_fork_in_child).
        self._inherited_connections: list[Any] = []
        self._last_holder_log: float | None = None

    @property
    def application_name(self) -> str:
        return self._fixed_application_name or default_application_name()

    @property
    def _backend_pid(self) -> int | None:
        return self._session[0] if self._session else None

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
            _warn_deprecated_settings()
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
                # Nothing is ever terminated at startup. A session this process lost can't exist yet.
                acquired, holder = self._take_lock()
                if not acquired and self._is_from_this_host(holder):
                    acquired, holder = self._wait_for_previous_run(holder)
                return acquired, holder
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

    def _is_from_this_host(self, holder: dict[str, Any] | None) -> bool:
        ours = _host_prefix(self.application_name)
        return holder is not None and ours is not None and str(holder.get("application_name") or "").startswith(ours)

    def _wait_for_previous_run(self, holder: dict[str, Any] | None) -> tuple[bool, dict[str, Any] | None]:
        """
        Wait up to PREVIOUS_RUN_WAIT_SECONDS for a holder from this host to go away, then try the lock again.

        It's most likely this container's daphne from before supervisord restarted it, whose session Postgres hasn't
        dropped yet because the close never got there. It could also be a second process on this host, which is why
        it's waited out and never terminated.
        """
        logger.warning(
            "Runtime lock: held by %s from this host, likely an earlier run whose session Postgres hasn't dropped "
            "yet. Waiting up to %ss for it before starting as a standby",
            describe_holder(holder),
            PREVIOUS_RUN_WAIT_SECONDS,
        )
        deadline = time.monotonic() + PREVIOUS_RUN_WAIT_SECONDS
        while time.monotonic() < deadline:
            time.sleep(PREVIOUS_RUN_POLL_SECONDS)
            if self._try_lock():
                logger.warning("Runtime lock: the earlier holder went away, took the lock")
                return True, None
            current = self._query_holder()
            if current is not None:
                holder = current
                if not self._is_from_this_host(current):
                    return False, current
        return False, holder

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
        pid, started = self._fetch_one(_OWN_SESSION_SQL)
        self._session = (int(pid), started)
        self._register_fork_hook()

    def _try_lock(self) -> bool:
        return bool(self._fetch_one(_TRY_LOCK_SQL, [LOCK_NAMESPACE, LOCK_KEY])[0])

    def _take_lock(self, *, lost_session: tuple[int, str | None] | None = None) -> tuple[bool, dict[str, Any] | None]:
        """
        Try the lock on the open connection. Returns whether it was taken, and the holder when it wasn't.

        `lost_session` is the session the heartbeat just lost. If that exact session (same backend pid and start
        time) still holds the lock, Postgres hasn't noticed it's dead yet, so it's terminated and the lock tried
        again, for up to STALE_SESSION_WAIT_SECONDS. Any other holder is left alone, whatever its name says.
        """
        deadline = time.monotonic() + STALE_SESSION_WAIT_SECONDS
        while True:
            if self._try_lock():
                return True, None
            holder = self._query_holder()
            if holder is not None and not _is_session(holder, lost_session):
                return False, holder
            if time.monotonic() >= deadline:
                return False, holder
            if holder is not None:
                logger.warning(
                    "Runtime lock: still held by the session this process just lost (backend pid %s), which "
                    "Postgres hasn't dropped yet, terminating it",
                    holder.get("pid"),
                )
                self._fetch_one("SELECT pg_terminate_backend(%s)", [holder.get("pid")])
            time.sleep(STALE_SESSION_RETRY_SECONDS)

    def _query_holder(self) -> dict[str, Any] | None:
        row = self._fetch_one(_HOLDER_SQL, [LOCK_NAMESPACE, LOCK_KEY])
        if not row:
            return None
        return {
            "pid": row[0],
            "application_name": row[1] or None,
            "client_addr": row[2] or None,
            "backend_start": row[3],
        }

    def _fetch_one(self, sql: str, params: list[Any] | None = None) -> Any:
        with self._conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def _ping(self) -> None:
        self._fetch_one("SELECT 1")

    def _drop_connection(self) -> None:
        conn, self._conn = self._conn, None
        self._session = None
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
        # The lock went with the session. Closing the old connection makes sure of that, if it's still there. If
        # Postgres still has it (the close never got there), it's the one session _take_lock may terminate.
        lost_session = self._session
        self._drop_connection()

        attempt = 0
        while not self._stop.is_set():
            attempt += 1
            try:
                self._open_connection()
                acquired, holder = self._take_lock(lost_session=lost_session)
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
        """
        Every tick, see whether the lock is still held. Once it's free, exit so supervisord restarts this process
        and it takes the lock, since the runtimes can only start from `ready()`. That's what gets a process that
        went standby behind a session Postgres was slow to drop running again. The ERROR naming the holder only
        goes out every HOLDER_LOG_SECONDS.
        """
        now = time.monotonic()
        log_due = self._last_holder_log is None or now - self._last_holder_log >= HOLDER_LOG_SECONDS
        try:
            if self._conn is None:
                self._open_connection()
            holder = self._query_holder()
        except Exception as exc:
            self._drop_connection()
            if log_due:
                self._last_holder_log = now
                logger.error(
                    "Runtime lock: this process is a standby and starts no runtimes, and checking who holds the "
                    "lock failed (%s). Run one process per database (ADR-0112)",
                    exc,
                )
            return
        if holder is None:
            logger.critical(
                "Runtime lock: the lock is free now and this process is a standby running no runtimes, so it exits "
                "to restart and take the lock (ADR-0112)"
            )
            _exit_process()
            return
        with self._mutex:
            self._holder = holder
        if log_due:
            self._last_holder_log = now
            self._log_standby(holder)

    def _log_standby(self, holder: dict[str, Any] | None) -> None:
        if holder is None:
            logger.error(
                "Runtime lock: the lock went free while this process checked it, so it's a standby for now and runs "
                "no runtimes. It restarts to take the lock on its next heartbeat (ADR-0112)"
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
                return {"state": HELD_ELSEWHERE, "holder": _public_holder(self._holder)}
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


def _warn_deprecated_settings() -> None:
    for name in _DEPRECATED_SETTINGS:
        if name in os.environ or hasattr(settings, name):
            logger.warning(
                "%s is set but doesn't do anything anymore. The scheduler runs only in the process that holds the "
                "runtime lock now (ADR-0112), so it can be removed",
                name,
            )


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
