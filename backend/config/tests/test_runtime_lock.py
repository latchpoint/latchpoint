"""The runtime lock: one runtime process per database (ADR-0112, #162)."""

from __future__ import annotations

import asyncio
import gc
import importlib
import logging
import os
import sys
import threading
import time
import unittest
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.db import OperationalError, connection
from django.test import SimpleTestCase, TestCase, override_settings

from config import runtime_lock
from config import settings as settings_module
from config.runtime_lock import (
    LOCK_KEY,
    LOCK_NAMESPACE,
    RuntimeLock,
    RuntimeLockUnavailable,
)
from config.runtimes import should_start_runtimes

NAME_A = "latchpoint-runtime:host-a:101:aaaaaa"
NAME_B = "latchpoint-runtime:host-b:202:bbbbbb"
NAME_C = "latchpoint-runtime:host-c:303:cccccc"
# Another process on host-a: a sibling container with the same hostname, or this container's daphne before a restart.
SIBLING = {"pid": 88, "application_name": "latchpoint-runtime:host-a:999:dddddd", "client_addr": None}
OTHER_HOLDER = {"pid": 77, "application_name": "latchpoint-runtime:other:9", "client_addr": "10.0.0.5"}
SERVER = ["daphne", "config.asgi:application"]


# -- a fake Postgres, for everything but the Postgres tests at the bottom ---------------------------------------


class _FakeCursor:
    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn
        self._row: Any = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        if self._conn.broken or self._conn.closed:
            raise OperationalError("server closed the connection unexpectedly")
        self._conn.executed.append((sql.strip(), params))
        self._row = self._conn.answer(sql, params)

    def fetchone(self) -> Any:
        return self._row


class _FakeConnection:
    def __init__(self, server: _FakeServer, *, backend_pid: int, application_name: str) -> None:
        self.server = server
        self.backend_pid = backend_pid
        # extract(epoch FROM backend_start)
        self.backend_start = Decimal("1793361600.123456") + backend_pid
        self.application_name = application_name
        self.autocommit = False
        self.closed = False
        self.broken = False
        self.executed: list[tuple[str, Any]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def answer(self, sql: str, params: list[Any] | None) -> Any:
        if "pg_terminate_backend" in sql:
            return (self.server.terminate(params[0]),)
        if "pg_backend_pid" in sql:
            return (self.backend_pid, self.backend_start)
        if "pg_try_advisory_lock" in sql:
            return (self.server.try_lock(self),)
        if "pg_locks" in sql:
            return self.server.holder_row()
        return (1,)

    def close(self) -> None:
        self.closed = True
        # A close on a broken connection never reaches the server, so the session (and lock) stay there.
        if not self.broken:
            self.server.release(self)


class _FakeServer:
    """Stands in for `connections["default"]`, with one advisory lock."""

    def __init__(self, vendor: str = "postgresql", options: str | None = None) -> None:
        self.vendor = vendor
        self.options = options
        self.holder: _FakeConnection | dict[str, Any] | None = None
        self.connections: list[_FakeConnection] = []
        self.params: list[dict[str, Any]] = []
        self.fail_connects = 0
        # When set, a dict holder goes away after this many more failed tries, ie Postgres dropping a dead session.
        self.holder_gone_after_tries: int | None = None
        self.terminated: list[int] = []

    def get_connection_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"dbname": "latchpoint"}
        if self.options:
            params["options"] = self.options
        return params

    def get_new_connection(self, params: dict[str, Any]) -> _FakeConnection:
        self.params.append(dict(params))
        if self.fail_connects:
            self.fail_connects -= 1
            raise OperationalError("could not connect to server")
        conn = _FakeConnection(
            self, backend_pid=1000 + len(self.connections), application_name=params["application_name"]
        )
        self.connections.append(conn)
        return conn

    def try_lock(self, conn: _FakeConnection) -> bool:
        if self.holder is None:
            self.holder = conn
        elif self.holder is not conn and self.holder_gone_after_tries is not None:
            if self.holder_gone_after_tries <= 0:
                self.holder = conn
                self.holder_gone_after_tries = None
            else:
                self.holder_gone_after_tries -= 1
        return self.holder is conn

    def holder_row(self) -> tuple[Any, ...] | None:
        holder = self.holder
        if holder is None:
            return None
        if isinstance(holder, _FakeConnection):
            return (holder.backend_pid, holder.application_name, None, holder.backend_start)
        return (holder["pid"], holder["application_name"], holder["client_addr"], holder.get("backend_start"))

    def release(self, conn: _FakeConnection) -> None:
        if self.holder is conn:
            self.holder = None

    def kill(self, conn: _FakeConnection) -> None:
        """The session ends under the client, ie a DB restart or pg_terminate_backend."""
        conn.broken = True
        self.release(conn)

    def lose(self, conn: _FakeConnection) -> None:
        """The client loses the connection but Postgres still has the session, lock and all (ie a lost FIN)."""
        conn.broken = True

    def terminate(self, pid: int) -> bool:
        self.terminated.append(pid)
        holder = self.holder
        if isinstance(holder, dict) and holder["pid"] == pid:
            self.holder = None
            return True
        if isinstance(holder, _FakeConnection) and holder.backend_pid == pid:
            self.kill(holder)
            return True
        return False


@override_settings(RUNTIME_LOCK="auto")
class _FakeServerTestCase(SimpleTestCase):
    def setUp(self) -> None:
        self.server = _FakeServer()
        self._patch(patch.object(runtime_lock, "connections", {"default": self.server}))
        self.register_at_fork = self._patch(patch.object(runtime_lock.os, "register_at_fork"))
        self.exit = self._patch(patch.object(runtime_lock.os, "_exit"))
        # The test runner isn't a server. Most tests here stand in for one, NonServerProcessTests doesn't.
        self.is_server = self._patch(patch.object(runtime_lock, "_is_server_process", return_value=True))
        self._patch(patch.object(runtime_lock, "STARTUP_RETRY_SECONDS", 0))
        self._patch(patch.object(runtime_lock, "STALE_SESSION_RETRY_SECONDS", 0))
        self._patch(patch.object(runtime_lock, "STALE_SESSION_WAIT_SECONDS", 1))
        self._patch(patch.object(runtime_lock, "RECONNECT_RETRY_SECONDS", 0))
        self._patch(patch.object(runtime_lock, "PREVIOUS_RUN_POLL_SECONDS", 0.001))
        self._patch(patch.object(runtime_lock, "PREVIOUS_RUN_WAIT_SECONDS", 0.05))
        # So a stray one in the env can't add a deprecation warning to every test.
        self._patch(patch.dict(os.environ))
        for name in ("SCHEDULER_LEADER_LOCK_ENABLED", "SCHEDULER_LEADER_LOCK_ID"):
            os.environ.pop(name, None)

    def _patch(self, patcher):
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def make(self, name: str = NAME_A) -> RuntimeLock:
        lock = RuntimeLock(application_name=name, start_heartbeat=False)
        self.addCleanup(lock.close)
        return lock

    def lock_held_elsewhere(self, holder: dict[str, Any] | None = None) -> RuntimeLock:
        self.server.holder = dict(holder or OTHER_HOLDER)
        lock = self.make()
        with self.assertLogs("config.runtime_lock", "ERROR"):
            self.assertFalse(lock.acquire_for_process())
        return lock


class RuntimeLockTests(_FakeServerTestCase):
    def test_takes_the_lock_on_its_own_connection(self):
        lock = self.make()

        self.assertTrue(lock.acquire_for_process())

        self.assertEqual(lock.get_status(), {"state": "active", "application_name": NAME_A})
        self.assertFalse(lock.is_held_elsewhere())
        [conn] = self.server.connections
        self.assertTrue(conn.autocommit)
        self.assertIn(("SELECT pg_try_advisory_lock(%s, %s)", [LOCK_NAMESPACE, LOCK_KEY]), conn.executed)
        self.assertEqual(LOCK_KEY, 1)
        # Fits a Postgres int4, so the two-int form takes it.
        self.assertLess(LOCK_NAMESPACE, 2**31)

    def test_connection_has_application_name_and_keepalives(self):
        self.make().acquire_for_process()

        [params] = self.server.params
        self.assertEqual(params["application_name"], NAME_A)
        self.assertEqual(
            params["options"], "-c tcp_keepalives_idle=10 -c tcp_keepalives_interval=5 -c tcp_keepalives_count=3"
        )
        self.assertEqual(params["keepalives"], 1)
        self.assertEqual(params["connect_timeout"], runtime_lock.CONNECT_TIMEOUT_SECONDS)

    def test_options_from_the_database_settings_are_kept(self):
        self.server.options = "-c search_path=latchpoint"

        self.make().acquire_for_process()

        self.assertTrue(self.server.params[0]["options"].startswith("-c search_path=latchpoint -c tcp_keepalives"))

    def test_default_application_name_has_the_host_pid_and_a_boot_token(self):
        with patch.object(runtime_lock.socket, "gethostname", return_value="x" * 100):
            name = runtime_lock.default_application_name()
            again = runtime_lock.default_application_name()

        prefix, host, pid, token = name.split(":")
        self.assertEqual(prefix, "latchpoint-runtime")
        self.assertTrue(host.startswith("xxx"))
        self.assertEqual(pid, str(os.getpid()))
        self.assertRegex(token, r"^[0-9a-f]{6}$")
        self.assertLessEqual(len(name), 63)
        # Stable within the process.
        self.assertEqual(again, name)

    def test_boot_token_differs_per_process(self):
        # Same pid, but a fresh process each time (an empty `_boot_tokens`), ie 2 sibling containers.
        with (
            patch.object(runtime_lock.os, "getpid", return_value=1),
            patch.object(runtime_lock.secrets, "token_hex", side_effect=["aaaaaa", "ffffff"]),
        ):
            with patch.object(runtime_lock, "_boot_tokens", {}):
                first = runtime_lock._boot_token()
                self.assertEqual(runtime_lock._boot_token(), first)
            with patch.object(runtime_lock, "_boot_tokens", {}):
                second = runtime_lock._boot_token()

        self.assertEqual((first, second), ("aaaaaa", "ffffff"))

    def test_non_ascii_hostname_becomes_what_postgres_would_report(self):
        # Postgres keeps only printable ASCII in an application_name, so the name is built that way already.
        with patch.object(runtime_lock.socket, "gethostname", return_value="küche:1"):
            name = runtime_lock.default_application_name()

        self.assertTrue(name.startswith("latchpoint-runtime:k?che?1:"))
        self.assertTrue(name.isascii())

    def test_held_elsewhere_starts_nothing_and_names_the_holder(self):
        self.server.holder = dict(OTHER_HOLDER)
        lock = self.make()

        with self.assertLogs("config.runtime_lock", "ERROR") as logs:
            self.assertFalse(lock.acquire_for_process())

        self.assertEqual(lock.get_status(), {"state": "held_elsewhere", "holder": OTHER_HOLDER})
        self.assertTrue(lock.is_held_elsewhere())
        self.assertIn("latchpoint-runtime:other:9 (backend pid 77, from 10.0.0.5)", logs.output[0])
        self.assertIn("standby", logs.output[0])

    def test_off_starts_the_runtimes_without_a_connection(self):
        lock = self.make()

        with override_settings(RUNTIME_LOCK="off"):
            self.assertTrue(lock.acquire_for_process())

        self.assertEqual(lock.get_status(), {"state": "disabled", "reason": "RUNTIME_LOCK=off"})
        self.assertEqual(self.server.params, [])

    def test_skipped_on_sqlite(self):
        self.server.vendor = "sqlite"
        lock = self.make()

        self.assertTrue(lock.acquire_for_process())

        self.assertEqual(lock.get_status()["state"], "disabled")
        self.assertIn("sqlite", lock.get_status()["reason"])
        self.assertEqual(self.server.params, [])

    def test_unknown_value_is_treated_as_auto(self):
        lock = self.make()

        with override_settings(RUNTIME_LOCK="sometimes"), self.assertLogs("config.runtime_lock", "WARNING") as logs:
            self.assertTrue(lock.acquire_for_process())

        self.assertIn("RUNTIME_LOCK='sometimes'", logs.output[0])
        self.assertEqual(lock.get_status()["state"], "active")

    def test_decided_once_per_process(self):
        lock = self.make()
        self.assertTrue(lock.acquire_for_process())
        # Even if it'd come out differently now, every later caller gets the first answer.
        self.server.holder = dict(OTHER_HOLDER)

        self.assertTrue(lock.acquire_for_process())
        self.assertTrue(lock.acquire_for_process())

        self.assertEqual(len(self.server.params), 1)

    def test_standby_is_decided_once_too(self):
        lock = self.lock_held_elsewhere()
        self.server.holder = None

        self.assertFalse(lock.acquire_for_process())

        self.assertEqual(len(self.server.params), 1)

    def test_not_checked_yet_reads_as_disabled(self):
        self.assertEqual(
            self.make().get_status(), {"state": "disabled", "reason": "runtimes aren't started in this process"}
        )

    def test_another_process_is_never_terminated(self):
        lock = self.lock_held_elsewhere()

        self.assertEqual(self.server.terminated, [])
        self.assertTrue(lock.is_held_elsewhere())

    def test_holder_from_another_host_means_standby_right_away(self):
        self.lock_held_elsewhere()

        tries = [sql for sql, _ in self.server.connections[0].executed if "pg_try_advisory_lock" in sql]
        self.assertEqual(len(tries), 1)


class StartupHolderFromThisHostTests(_FakeServerTestCase):
    """
    A holder from this same host is most likely this container's daphne before supervisord restarted it, whose
    session Postgres hasn't dropped yet. It's waited out for PREVIOUS_RUN_WAIT_SECONDS, never terminated.
    """

    def test_takes_the_lock_once_the_previous_run_goes_away(self):
        self.server.holder = dict(SIBLING)
        self.server.holder_gone_after_tries = 3
        lock = self.make()

        with self.assertLogs("config.runtime_lock", "WARNING") as logs:
            self.assertTrue(lock.acquire_for_process())

        self.assertEqual(lock.get_status()["state"], "active")
        self.assertIn("latchpoint-runtime:host-a:999:dddddd", logs.output[0])
        self.assertEqual(self.server.terminated, [])

    def test_a_holder_that_stays_means_standby_and_is_never_terminated(self):
        # ie a live sibling container with the same hostname.
        self.server.holder = dict(SIBLING)
        lock = self.make()

        with self.assertLogs("config.runtime_lock", "WARNING") as logs:
            self.assertFalse(lock.acquire_for_process())

        self.assertEqual(lock.get_status(), {"state": "held_elsewhere", "holder": SIBLING})
        self.assertEqual(self.server.terminated, [])
        self.assertTrue(any("standby" in line for line in logs.output))

    def test_same_host_and_pid_but_another_process(self):
        # 2 containers whose hostname and pid match. Only the boot token tells their names apart, and neither ever
        # terminates the other.
        twin = {"pid": 66, "application_name": "latchpoint-runtime:host-a:101:eeeeee", "client_addr": None}
        self.server.holder = dict(twin)
        lock = self.make()

        with self.assertLogs("config.runtime_lock", "WARNING"):
            self.assertFalse(lock.acquire_for_process())

        self.assertEqual(lock.get_status()["holder"], twin)
        self.assertEqual(self.server.terminated, [])

    def test_even_an_identical_name_is_never_terminated(self):
        self.server.holder = {"pid": 66, "application_name": NAME_A, "client_addr": None}
        lock = self.make()

        with self.assertLogs("config.runtime_lock", "WARNING"):
            self.assertFalse(lock.acquire_for_process())

        self.assertEqual(self.server.terminated, [])

    def test_unreachable_database_at_startup_retries_then_raises(self):
        self.server.fail_connects = 99
        lock = self.make()

        with self.assertLogs("config.runtime_lock", "WARNING"), self.assertRaises(RuntimeLockUnavailable):
            lock.acquire_for_process()

        self.assertEqual(len(self.server.params), runtime_lock.STARTUP_ATTEMPTS)

    def test_database_coming_up_during_the_startup_retries(self):
        self.server.fail_connects = 2
        lock = self.make()

        with self.assertLogs("config.runtime_lock", "WARNING"):
            self.assertTrue(lock.acquire_for_process())

        self.assertEqual(len(self.server.params), 3)
        self.assertEqual(lock.get_status()["state"], "active")

    def test_close_frees_the_lock(self):
        lock = self.make()
        lock.acquire_for_process()

        lock.close()

        self.assertIsNone(self.server.holder)


class TimingTests(SimpleTestCase):
    def test_startup_waits_out_the_server_keepalives(self):
        ka = runtime_lock.SERVER_KEEPALIVES
        dropped_after = ka["tcp_keepalives_idle"] + ka["tcp_keepalives_interval"] * ka["tcp_keepalives_count"]

        self.assertEqual(dropped_after, 25)
        self.assertGreater(runtime_lock.PREVIOUS_RUN_WAIT_SECONDS, dropped_after)
        self.assertLessEqual(runtime_lock.PREVIOUS_RUN_WAIT_SECONDS, 40)


class HeartbeatTests(_FakeServerTestCase):
    def test_healthy_tick_only_pings(self):
        lock = self.make()
        lock.acquire_for_process()

        lock.heartbeat_once()

        [conn] = self.server.connections
        self.assertEqual(conn.executed[-1], ("SELECT 1", None))
        self.assertEqual(lock.get_status()["state"], "active")

    def test_takes_the_lock_again_after_losing_the_connection(self):
        lock = self.make()
        lock.acquire_for_process()
        self.server.kill(self.server.connections[0])

        with self.assertLogs("config.runtime_lock", "WARNING") as logs:
            lock.heartbeat_once()

        self.assertEqual(lock.get_status()["state"], "active")
        self.assertIs(self.server.holder, self.server.connections[1])
        self.assertIn("took the lock again", logs.output[-1])
        self.exit.assert_not_called()

    def test_exits_when_another_process_took_the_lock_meanwhile(self):
        lock = self.make()
        lock.acquire_for_process()
        self.server.kill(self.server.connections[0])
        self.server.holder = dict(OTHER_HOLDER)

        with self.assertLogs("config.runtime_lock", "CRITICAL") as logs:
            lock.heartbeat_once()

        self.exit.assert_called_once_with(1)
        self.assertIn("latchpoint-runtime:other:9", logs.output[-1])
        self.assertEqual(lock.get_status(), {"state": "held_elsewhere", "holder": OTHER_HOLDER})

    def test_keeps_trying_while_the_database_is_down(self):
        lock = self.make()
        lock.acquire_for_process()
        self.server.kill(self.server.connections[0])
        self.server.fail_connects = 3

        with self.assertLogs("config.runtime_lock", "WARNING"):
            lock.heartbeat_once()

        self.assertEqual(len(self.server.params), 5)
        self.assertEqual(lock.get_status()["state"], "active")
        self.exit.assert_not_called()

    def test_standby_logs_the_holder_every_5_minutes(self):
        lock = self.lock_held_elsewhere()

        lock._last_holder_log = time.monotonic() - runtime_lock.HOLDER_LOG_SECONDS + 30
        with self.assertNoLogs("config.runtime_lock", "ERROR"):
            lock.heartbeat_once()

        lock._last_holder_log = time.monotonic() - runtime_lock.HOLDER_LOG_SECONDS - 1
        with self.assertLogs("config.runtime_lock", "ERROR") as logs:
            lock.heartbeat_once()
        self.assertIn("latchpoint-runtime:other:9", logs.output[0])
        self.exit.assert_not_called()

    def test_standby_checks_every_tick_and_exits_once_the_lock_is_free(self):
        # Right after startup, well inside the 5 minutes between ERROR lines, so this is the check, not the log.
        lock = self.lock_held_elsewhere()
        with self.assertNoLogs("config.runtime_lock", "ERROR"):
            lock.heartbeat_once()
        self.exit.assert_not_called()
        self.server.holder = None

        with self.assertLogs("config.runtime_lock", "CRITICAL") as logs:
            lock.heartbeat_once()

        self.exit.assert_called_once_with(1)
        self.assertIn("free now", logs.output[0])
        # It exits to take the lock when it comes back, it doesn't take it here.
        self.assertIsNone(self.server.holder)

    def test_false_standby_behind_a_lingering_session_recovers(self):
        # Startup found this container's previous daphne still holding the lock and it outlasted the wait, ie
        # Postgres was slower than usual dropping it. Once it's gone the standby exits and comes back to take it.
        self.server.holder = dict(SIBLING)
        lock = self.make()
        with self.assertLogs("config.runtime_lock", "WARNING"):
            self.assertFalse(lock.acquire_for_process())
        self.server.holder = None

        with self.assertLogs("config.runtime_lock", "CRITICAL"):
            lock.heartbeat_once()

        self.exit.assert_called_once_with(1)
        self.assertEqual(self.server.terminated, [])

    def test_standby_reconnects_when_its_connection_is_gone(self):
        lock = self.lock_held_elsewhere()
        self.server.kill(self.server.connections[0])

        lock.heartbeat_once()
        lock.heartbeat_once()

        self.assertEqual(len(self.server.params), 2)
        self.exit.assert_not_called()
        self.assertTrue(lock.is_held_elsewhere())


class NonServerProcessTests(_FakeServerTestCase):
    """
    A management command with START_RUNTIMES=true (ie `run_task`, `shell`) never exits from the heartbeat. Nothing
    would bring it back and it'd die mid-task, so it logs instead.
    """

    def setUp(self) -> None:
        super().setUp()
        self.is_server.return_value = False

    def test_standby_logs_instead_of_exiting_once_the_lock_is_free(self):
        lock = self.lock_held_elsewhere()
        self.server.holder = None
        lock._last_holder_log = None

        with self.assertLogs("config.runtime_lock", "ERROR") as logs:
            lock.heartbeat_once()

        self.exit.assert_not_called()
        self.assertIn("isn't a server", logs.output[0])
        self.assertTrue(lock.is_held_elsewhere())
        # And it doesn't take the lock either, its runtimes never started.
        self.assertIsNone(self.server.holder)

    def test_standby_free_lock_log_is_rate_limited(self):
        lock = self.lock_held_elsewhere()
        self.server.holder = None

        with self.assertNoLogs("config.runtime_lock", "ERROR"):
            lock.heartbeat_once()

        self.exit.assert_not_called()

    def test_lost_lock_logs_instead_of_exiting(self):
        lock = self.make()
        lock.acquire_for_process()
        self.server.kill(self.server.connections[0])
        self.server.holder = dict(OTHER_HOLDER)

        with self.assertLogs("config.runtime_lock", "CRITICAL") as logs:
            lock.heartbeat_once()

        self.exit.assert_not_called()
        self.assertIn("isn't a server, so it doesn't exit", logs.output[-1])
        self.assertTrue(lock.is_held_elsewhere())


class IsServerProcessTests(SimpleTestCase):
    def test_uses_the_server_argv_check(self):
        cases = [
            (["daphne", "-b", "127.0.0.1", "config.asgi:application"], True),
            (["manage.py", "run_task", "push_requested_door_codes"], False),
            (["manage.py", "shell"], False),
            (["manage.py", "test"], False),
        ]
        for argv, expected in cases:
            with self.subTest(argv=argv), patch.object(sys, "argv", argv):
                self.assertIs(runtime_lock._is_server_process(), expected)


class HeartbeatTerminatesOnlyItsOwnLostSessionTests(_FakeServerTestCase):
    """The only session the heartbeat ever terminates is the exact one it lost, matched on backend pid and start."""

    def test_lost_session_postgres_still_has_is_terminated(self):
        lock = self.make()
        lock.acquire_for_process()
        old = self.server.connections[0]
        self.server.lose(old)

        with self.assertLogs("config.runtime_lock", "WARNING") as logs:
            lock.heartbeat_once()

        self.assertEqual(self.server.terminated, [old.backend_pid])
        self.assertTrue(any("just lost" in line for line in logs.output))
        self.assertEqual(lock.get_status()["state"], "active")
        self.assertIs(self.server.holder, self.server.connections[1])
        self.exit.assert_not_called()

    def test_matched_by_session_even_if_postgres_rewrote_the_name(self):
        lock = self.make()
        lock.acquire_for_process()
        old = self.server.connections[0]
        old.application_name = "latchpoint-runtime:k\\xc3\\xbcche:101:aaaaaa"
        self.server.lose(old)

        with self.assertLogs("config.runtime_lock", "WARNING"):
            lock.heartbeat_once()

        self.assertEqual(self.server.terminated, [old.backend_pid])
        self.assertEqual(lock.get_status()["state"], "active")

    def test_sibling_on_the_same_host_is_never_terminated(self):
        lock = self.make()
        lock.acquire_for_process()
        self.server.kill(self.server.connections[0])
        self.server.holder = dict(SIBLING)

        with self.assertLogs("config.runtime_lock", "CRITICAL"):
            lock.heartbeat_once()

        self.assertEqual(self.server.terminated, [])
        self.exit.assert_called_once_with(1)

    def test_holder_with_our_name_but_another_session_is_never_terminated(self):
        # A twin with the same hostname and pid that somehow has our exact name too.
        lock = self.make()
        lock.acquire_for_process()
        self.server.kill(self.server.connections[0])
        self.server.holder = {"pid": 66, "application_name": NAME_A, "client_addr": None}

        with self.assertLogs("config.runtime_lock", "CRITICAL"):
            lock.heartbeat_once()

        self.assertEqual(self.server.terminated, [])
        self.exit.assert_called_once_with(1)

    def test_same_backend_pid_but_a_later_session_is_never_terminated(self):
        lock = self.make()
        lock.acquire_for_process()
        old = self.server.connections[0]
        self.server.kill(old)
        self.server.holder = {
            "pid": old.backend_pid,
            "application_name": SIBLING["application_name"],
            "client_addr": None,
            "backend_start": old.backend_start + 300,
        }

        with self.assertLogs("config.runtime_lock", "CRITICAL"):
            lock.heartbeat_once()

        self.assertEqual(self.server.terminated, [])

    def test_twins_stay_apart_and_only_one_ends_up_active(self):
        # Same hostname and pid, ie 2 containers started the same way. Before the fix each one terminated the
        # other's session as its own and both stayed active.
        a = self.make("latchpoint-runtime:host-a:101:aaaaaa")
        b = self.make("latchpoint-runtime:host-a:101:bbbbbb")
        self.assertTrue(a.acquire_for_process())
        with self.assertLogs("config.runtime_lock", "WARNING"):
            self.assertFalse(b.acquire_for_process())

        # a's connection drops but Postgres keeps the session, so a gets it back by terminating only that.
        self.server.lose(self.server.connections[0])
        with self.assertLogs("config.runtime_lock", "WARNING"):
            a.heartbeat_once()
        b.heartbeat_once()

        self.assertEqual(a.get_status()["state"], "active")
        self.assertEqual(b.get_status()["state"], "held_elsewhere")
        self.assertEqual(b.get_status()["holder"]["application_name"], "latchpoint-runtime:host-a:101:aaaaaa")
        self.assertEqual(self.server.terminated, [self.server.connections[0].backend_pid])
        self.exit.assert_not_called()

    def test_heartbeat_thread_runs_the_ticks(self):
        lock = RuntimeLock(application_name=NAME_A)
        self.addCleanup(lock.close)
        ticked = threading.Event()

        with (
            patch.object(runtime_lock, "HEARTBEAT_SECONDS", 0.01),
            patch.object(RuntimeLock, "heartbeat_once", side_effect=ticked.set),
        ):
            lock.acquire_for_process()
            self.assertTrue(ticked.wait(5))

        self.assertEqual(lock._thread.name, "runtime-lock-heartbeat")
        self.assertTrue(lock._thread.daemon)


class ForkTests(_FakeServerTestCase):
    def test_registers_the_child_hook(self):
        lock = self.make()
        lock.acquire_for_process()

        self.register_at_fork.assert_called_once_with(after_in_child=lock._after_fork_in_child)

    def test_child_logs_and_never_touches_the_inherited_connection(self):
        lock = self.make()
        lock.acquire_for_process()
        [conn] = self.server.connections
        executed = list(conn.executed)

        with self.assertLogs("config.runtime_lock", "CRITICAL") as logs:
            lock._after_fork_in_child()

        self.assertIn("forked", logs.output[0])
        self.assertFalse(conn.closed)
        self.assertEqual(conn.executed, executed)
        # Kept referenced, out of reach of close() and the heartbeat.
        self.assertEqual(lock._inherited_connections, [conn])
        self.assertTrue(lock.is_held_elsewhere())
        self.assertEqual(lock.get_status()["holder"]["application_name"], NAME_A)
        self.assertFalse(lock.acquire_for_process())
        lock.close()
        self.assertFalse(conn.closed)
        self.assertIs(self.server.holder, conn)

    def test_fork_with_no_connection_is_quiet(self):
        lock = self.make()
        with override_settings(RUNTIME_LOCK="off"):
            lock.acquire_for_process()

        with self.assertNoLogs("config.runtime_lock", "CRITICAL"):
            lock._after_fork_in_child()

        self.assertEqual(lock.get_status()["state"], "disabled")


class EventLoopTests(SimpleTestCase):
    """uvicorn runs `ready()` inside its event loop, where Django won't open a connection."""

    def test_runs_in_place_without_a_loop(self):
        self.assertIs(runtime_lock._call_outside_event_loop(threading.current_thread), threading.current_thread())

    def test_runs_in_another_thread_inside_a_loop(self):
        async def _main():
            return threading.current_thread(), runtime_lock._call_outside_event_loop(threading.current_thread)

        here, there = asyncio.run(_main())

        self.assertIsNot(here, there)

    def test_errors_come_through(self):
        def _boom():
            raise RuntimeLockUnavailable("down")

        async def _main():
            runtime_lock._call_outside_event_loop(_boom)

        with self.assertRaises(RuntimeLockUnavailable):
            asyncio.run(_main())


class DeprecatedSettingsTests(_FakeServerTestCase):
    """The scheduler's old leader lock settings are gone, and setting them says so (#162)."""

    def test_old_env_vars_log_a_deprecation_warning(self):
        for name in ("SCHEDULER_LEADER_LOCK_ENABLED", "SCHEDULER_LEADER_LOCK_ID"):
            with (
                self.subTest(name=name),
                patch.dict(os.environ, {name: "1"}),
                self.assertLogs("config.runtime_lock", "WARNING") as logs,
            ):
                self.make().acquire_for_process()
            self.assertIn(name, logs.output[0])
            self.assertIn("doesn't do anything anymore", logs.output[0])

    def test_old_setting_logs_a_deprecation_warning(self):
        with (
            override_settings(SCHEDULER_LEADER_LOCK_ENABLED=True),
            self.assertLogs("config.runtime_lock", "WARNING") as logs,
        ):
            self.make().acquire_for_process()

        self.assertIn("SCHEDULER_LEADER_LOCK_ENABLED", logs.output[0])

    def test_nothing_logged_without_them(self):
        with self.assertNoLogs("config.runtime_lock", "WARNING"):
            self.make().acquire_for_process()

    def test_settings_are_gone(self):
        from django.conf import settings

        self.assertFalse(hasattr(settings, "SCHEDULER_LEADER_LOCK_ENABLED"))
        self.assertFalse(hasattr(settings, "SCHEDULER_LEADER_LOCK_ID"))


class RuntimeLockSettingUnderTestsTests(SimpleTestCase):
    """`RUNTIME_LOCK` from the env doesn't reach a test run, so only a test that asks for the lock takes it."""

    def tearDown(self):
        importlib.reload(settings_module)

    def test_the_env_var_is_ignored_under_tests(self):
        with patch.dict(os.environ, {"RUNTIME_LOCK": "auto"}):
            importlib.reload(settings_module)

        self.assertTrue(settings_module.IS_TESTING)
        self.assertEqual(settings_module.RUNTIME_LOCK, "off")

    def test_the_env_var_is_read_outside_tests(self):
        pytest_module = sys.modules.pop("pytest", None)
        try:
            with (
                patch.dict(os.environ, {"RUNTIME_LOCK": "auto"}),
                patch.object(sys, "argv", ["daphne", "config.asgi:application"]),
            ):
                importlib.reload(settings_module)
        finally:
            if pytest_module is not None:
                sys.modules["pytest"] = pytest_module

        self.assertFalse(settings_module.IS_TESTING)
        self.assertEqual(settings_module.RUNTIME_LOCK, "auto")


class _ProcessLockTestCase(_FakeServerTestCase):
    """Swaps in the module's own per-process lock."""

    def use_process_lock(self, lock: RuntimeLock) -> RuntimeLock:
        self._patch(patch.object(runtime_lock, "_process_lock", lock))
        return lock


@override_settings(START_RUNTIMES="auto")
class ShouldStartRuntimesUsesTheLockTests(_ProcessLockTestCase):
    def test_server_in_a_standby_starts_nothing(self):
        self.server.holder = dict(OTHER_HOLDER)
        self.use_process_lock(self.make())

        with self.assertLogs("config.runtime_lock", "ERROR"):
            self.assertFalse(should_start_runtimes(SERVER))
        # Every app's ready() after the first gets the same answer.
        self.assertFalse(should_start_runtimes(SERVER))
        self.assertEqual(len(self.server.params), 1)

    def test_server_holding_the_lock_starts_them(self):
        self.use_process_lock(self.make())

        self.assertTrue(should_start_runtimes(SERVER))
        self.assertTrue(should_start_runtimes(SERVER))

        self.assertEqual(len(self.server.params), 1)

    def test_start_runtimes_true_still_needs_the_lock(self):
        self.server.holder = dict(OTHER_HOLDER)
        self.use_process_lock(self.make())

        with override_settings(START_RUNTIMES="true"), self.assertLogs("config.runtime_lock", "ERROR"):
            self.assertFalse(should_start_runtimes(["manage.py", "shell"]))

    def test_process_that_doesnt_want_runtimes_never_checks(self):
        lock = self.use_process_lock(self.make())

        self.assertFalse(should_start_runtimes(["manage.py", "migrate"]))
        with override_settings(START_RUNTIMES="false"):
            self.assertFalse(should_start_runtimes(SERVER))

        self.assertEqual(self.server.params, [])
        self.assertEqual(lock.get_status()["state"], "disabled")

    def test_off_under_tests_by_default(self):
        self.use_process_lock(self.make())

        with override_settings(RUNTIME_LOCK=settings_module.RUNTIME_LOCK):
            self.assertTrue(should_start_runtimes(SERVER))

        self.assertEqual(self.server.params, [])


class PushTaskRunningTests(_ProcessLockTestCase):
    """A standby only queues door code pushes, and the active process's tick sends them (ADR-0111, ADR-0112)."""

    def test_true_in_a_standby(self):
        from locks.use_cases.lock_push import push_task_running

        self.use_process_lock(self.lock_held_elsewhere())

        self.assertTrue(push_task_running())

    def test_unchanged_otherwise(self):
        from locks.use_cases.lock_push import push_task_running

        self.use_process_lock(self.make())

        self.assertFalse(push_task_running())
        with patch("scheduler.runner.is_task_running", return_value=True):
            self.assertTrue(push_task_running())


class SchedulerStatusTests(_ProcessLockTestCase):
    def test_has_the_runtime_lock(self):
        from scheduler.runner import get_scheduler_status

        self.use_process_lock(self.lock_held_elsewhere())

        status = get_scheduler_status()

        self.assertEqual(status["runtime_lock"], {"state": "held_elsewhere", "holder": OTHER_HOLDER})
        self.assertNotIn("leader_lock", status)


class SystemStatusTests(TestCase):
    def test_payload_has_the_runtime_block(self):
        from alarm.system_status import _compute_system_status_payload

        lock = RuntimeLock(application_name=NAME_A, start_heartbeat=False)
        lock._set_held_elsewhere(dict(OTHER_HOLDER))
        with patch.object(runtime_lock, "_process_lock", lock):
            payload = _compute_system_status_payload(include_home_assistant=False)

        self.assertEqual(payload["runtime"], {"state": "held_elsewhere", "holder": OTHER_HOLDER})

    def test_payload_says_disabled_under_tests(self):
        from alarm.system_status import _compute_system_status_payload

        with patch.object(runtime_lock, "_process_lock", RuntimeLock(start_heartbeat=False)):
            payload = _compute_system_status_payload(include_home_assistant=False)

        self.assertEqual(payload["runtime"]["state"], "disabled")


# -- real Postgres ------------------------------------------------------------------------------------------------


@unittest.skipUnless(connection.vendor == "postgresql", "needs Postgres")
@override_settings(RUNTIME_LOCK="auto")
class PostgresRuntimeLockTests(SimpleTestCase):
    """Dedicated connections against the test database. Each lock gets its own application_name."""

    databases = {"default"}

    def setUp(self) -> None:
        for patcher in (
            patch.object(runtime_lock.os, "register_at_fork"),
            patch.object(runtime_lock, "_is_server_process", return_value=True),
            patch.object(runtime_lock, "STALE_SESSION_RETRY_SECONDS", 0.1),
            patch.object(runtime_lock, "RECONNECT_RETRY_SECONDS", 0.1),
            patch.object(runtime_lock, "PREVIOUS_RUN_WAIT_SECONDS", 5),
            patch.object(runtime_lock, "PREVIOUS_RUN_POLL_SECONDS", 0.1),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make(self, name: str) -> RuntimeLock:
        lock = RuntimeLock(application_name=name, start_heartbeat=False)
        self.addCleanup(lock.close)
        return lock

    def _terminate(self, pid: int) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_terminate_backend(%s)", [pid])
        self._wait_gone(pid)

    def _wait_gone(self, pid: int) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_stat_activity WHERE pid = %s", [pid])
                if cursor.fetchone() is None:
                    return
            time.sleep(0.05)
        self.fail(f"backend {pid} is still there")

    def test_second_connection_gets_nothing_and_sees_the_holder(self):
        a = self.make(NAME_A)
        b = self.make(NAME_B)

        self.assertTrue(a.acquire_for_process())
        with self.assertLogs("config.runtime_lock", "ERROR") as logs:
            self.assertFalse(b.acquire_for_process())

        holder = b.get_status()["holder"]
        self.assertEqual(b.get_status()["state"], "held_elsewhere")
        self.assertEqual(holder["application_name"], NAME_A)
        self.assertEqual(holder["pid"], a._backend_pid)
        self.assertIn(NAME_A, logs.output[0])
        # Not Django's own connection.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            self.assertNotEqual(cursor.fetchone()[0], a._backend_pid)
        with a._conn.cursor() as cursor:
            cursor.execute("SELECT current_setting('application_name'), current_setting('tcp_keepalives_idle')")
            app_name, keepalives_idle = cursor.fetchone()
        self.assertEqual(app_name, NAME_A)
        if a._conn.info.host and not a._conn.info.host.startswith("/"):
            # Postgres reads it as 0 on a Unix socket.
            self.assertEqual(keepalives_idle, "10")

    def test_lock_is_freed_with_the_session(self):
        a = self.make(NAME_A)
        a.acquire_for_process()
        a.close()

        self.assertTrue(self.make(NAME_B).acquire_for_process())

    def test_heartbeat_takes_the_lock_again_after_the_holder_is_terminated(self):
        a = self.make(NAME_A)
        a.acquire_for_process()
        old_pid = a._backend_pid
        self._terminate(old_pid)

        with patch.object(runtime_lock.os, "_exit") as exit_, self.assertLogs("config.runtime_lock", "WARNING"):
            a.heartbeat_once()

        exit_.assert_not_called()
        self.assertEqual(a.get_status()["state"], "active")
        self.assertNotEqual(a._backend_pid, old_pid)
        with self.assertLogs("config.runtime_lock", "ERROR"):
            self.assertFalse(self.make(NAME_B).acquire_for_process())

    def test_heartbeat_exits_when_another_process_took_the_lock(self):
        a = self.make(NAME_A)
        a.acquire_for_process()
        self._terminate(a._backend_pid)
        c = self.make(NAME_C)
        self.assertTrue(c.acquire_for_process())

        with patch.object(runtime_lock.os, "_exit") as exit_, self.assertLogs("config.runtime_lock", "CRITICAL"):
            a.heartbeat_once()

        exit_.assert_called_once_with(1)
        self.assertEqual(a.get_status()["holder"]["application_name"], NAME_C)

    def test_heartbeat_terminates_our_own_session_postgres_hasnt_dropped(self):
        # ie a network blip: the client gave up on the connection but the server still has the session.
        a = self.make(NAME_A)
        a.acquire_for_process()
        old_conn, old_pid = a._conn, a._backend_pid
        self.addCleanup(old_conn.close)

        with (
            patch.object(a, "_ping", side_effect=OperationalError("timed out")),
            patch.object(a, "_close_quietly", lambda conn: None),
            patch.object(runtime_lock.os, "_exit") as exit_,
            self.assertLogs("config.runtime_lock", "WARNING") as logs,
        ):
            a.heartbeat_once()

        exit_.assert_not_called()
        self.assertTrue(any("just lost" in line for line in logs.output))
        self.assertEqual(a.get_status()["state"], "active")
        self._wait_gone(old_pid)

    def test_session_start_matches_whatever_the_datestyle_and_timezone(self):
        a = self.make(NAME_A)
        a.acquire_for_process()
        b = self.make(NAME_B)
        with self.assertLogs("config.runtime_lock", "ERROR"):
            b.acquire_for_process()
        # The text form of backend_start would come out different in b's session after this.
        with b._conn.cursor() as cursor:
            cursor.execute("SET TimeZone = 'Asia/Tokyo'")
            cursor.execute("SET DateStyle = 'German, DMY'")

        holder = b._query_holder()

        self.assertEqual(holder["pid"], a._backend_pid)
        self.assertEqual(holder["backend_start"], a._session[1])
        self.assertTrue(runtime_lock._is_session(holder, a._session))

    def test_startup_waits_out_a_previous_run_from_this_host(self):
        previous = self.make("latchpoint-runtime:pg-host:1111111:zzzzzz")
        self.assertTrue(previous.acquire_for_process())
        # Postgres drops it a moment later, the way the server keepalives would.
        threading.Timer(0.5, previous.close).start()
        restarted = self.make("latchpoint-runtime:pg-host:2222222:yyyyyy")

        with self.assertLogs("config.runtime_lock", "WARNING"):
            self.assertTrue(restarted.acquire_for_process())

        self.assertEqual(restarted.get_status()["state"], "active")

    def test_startup_never_terminates_a_holder_from_this_host(self):
        sibling = self.make("latchpoint-runtime:pg-host:1111111:zzzzzz")
        sibling.acquire_for_process()
        sibling_pid = sibling._backend_pid

        with patch.object(runtime_lock, "PREVIOUS_RUN_WAIT_SECONDS", 0.5), self.assertLogs("config.runtime_lock"):
            self.assertFalse(self.make("latchpoint-runtime:pg-host:2222222:yyyyyy").acquire_for_process())

        sibling._ping()
        self.assertEqual(sibling._backend_pid, sibling_pid)

    def test_standby_exits_once_the_holder_is_gone(self):
        holder = self.make(NAME_A)
        holder.acquire_for_process()
        standby = self.make(NAME_B)
        with self.assertLogs("config.runtime_lock", "ERROR"):
            standby.acquire_for_process()

        with patch.object(runtime_lock.os, "_exit") as exit_:
            standby.heartbeat_once()
            exit_.assert_not_called()
            holder.close()
            with self.assertLogs("config.runtime_lock", "CRITICAL"):
                standby.heartbeat_once()

        exit_.assert_called_once_with(1)

    def test_twins_with_the_same_host_and_pid_stay_apart(self):
        a = self.make("latchpoint-runtime:pg-host:101:aaaaaa")
        b = self.make("latchpoint-runtime:pg-host:101:bbbbbb")
        self.assertTrue(a.acquire_for_process())
        with patch.object(runtime_lock, "PREVIOUS_RUN_WAIT_SECONDS", 0.5), self.assertLogs("config.runtime_lock"):
            self.assertFalse(b.acquire_for_process())
        a_pid = a._backend_pid

        with patch.object(runtime_lock.os, "_exit") as exit_:
            a.heartbeat_once()
            b.heartbeat_once()

        exit_.assert_not_called()
        a._ping()
        self.assertEqual(a._backend_pid, a_pid)
        self.assertEqual(b.get_status()["holder"]["pid"], a_pid)

    @unittest.skipUnless(hasattr(os, "fork"), "needs fork")
    def test_forked_child_leaves_the_parents_lock_alone(self):
        a = self.make(NAME_A)
        a.acquire_for_process()

        pid = os.fork()
        if pid == 0:  # pragma: no cover - the child
            code = 0
            try:
                logging.disable(logging.CRITICAL)
                a._after_fork_in_child()
                # Closing the inherited connection here would end the parent's session, lock and all.
                a.close()
                gc.collect()
            except BaseException:
                code = 1
            os._exit(code)
        _, status = os.waitpid(pid, 0)

        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        a._ping()
        with self.assertLogs("config.runtime_lock", "ERROR"):
            self.assertFalse(self.make(NAME_B).acquire_for_process())
