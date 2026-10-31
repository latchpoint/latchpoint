# ADR-0112: One Runtime Process per Database

**Status:** Accepted
**Date:** 2026-10-30
**Author:** Leonardo Merza

**Supersedes:** the scheduler leader lock (`SCHEDULER_LEADER_LOCK_ENABLED`, `SCHEDULER_LEADER_LOCK_ID`) from ADR-0024's scheduler

## Context

Prod runs one daphne process under supervisord, with a per-process (locmem)
cache and `InMemoryChannelLayer`. Nothing stops a second process from running
against the same database though, ie a second container, a second daphne, or
gunicorn with more than one worker, and a lot of the code quietly assumes there's
only one (#162). The ones that matter for safety once there are 2 or more:

- **Re-arm guard.** `alarm/rearm_guard.py` keeps its marker in the cache, so in
  locmem every process has its own guard and a disarm in one doesn't block an
  arm in another.
- **Keypad and MQTT alarm codes.** Every process subscribes to the same MQTT and
  Z-Wave JS events, so each keypad or MQTT command is handled once per process,
  and a failed code counts once per process.
- **Throttles.** The `login` and `alarm_code` throttles keep their history in
  the cache, so they're N times looser with N processes. The account lockout is
  on the user row, so it isn't affected.
- **Broadcasts.** `InMemoryChannelLayer` only reaches websocket clients on the
  same process, so a "triggered" broadcast never reaches clients on the others.
- **Leaders.**
  - The HA state stream's leader key is in the cache, so in locmem every
    process is the leader and opens its own HA session.
  - The scheduler leader lock was off by default, so every process ran every
    scheduled task.
  - With it on, the lock was taken once on Django's thread-local connection in
    `ready()`. If that connection dropped the lock went with it without anyone
    noticing, and a process that didn't get it never tried again.
- **Signals.** `settings_profile_changed` (#122) and
  `alarm_state_change_committed` are in-process Django signals, so a settings
  save or a state change only reaches the receivers in the process that made it.
- **Startup.** The runtimes start from `AppConfig.ready()` (#160), and a server
  that forks after `ready()` (gunicorn `--preload`) loses those threads in its
  workers.

Fixing each of these for real multi-process means a shared cache, a shared
channel layer, a cross-process bus for the signals and leader election for every
runtime. There's no need for more than one process today, the load is a
household's worth of devices and a handful of browsers.

## Decision

Latchpoint supports exactly one runtime process per database, and enforces it
with a Postgres advisory lock.

- **The lock.** `backend/config/runtime_lock.py` takes
  `pg_try_advisory_lock(<namespace>, 1)` in the two-int form. The two-int key
  space doesn't overlap the single bigint one that `lock_sync:`
  (`locks/use_cases/lock_config_sync.py`) uses, so it can't collide with those.
  Advisory locks are per database, so 2 installs on one Postgres server don't
  block each other.
- **Where.** `should_start_runtimes()` (`config/runtimes.py`) checks it once per
  process, the first time a process that wants runtimes asks. The result sticks
  for the life of the process, so every app's `ready()` gets the same answer.
- **Dedicated connection.** It's opened with
  `connections["default"].get_new_connection(...)`, never Django's thread-local
  connection, so `close_old_connections()`, a request finishing or a thread
  exiting can't drop it. It runs in autocommit, with
  `application_name=latchpoint-runtime:<hostname>:<pid>:<boot token>`, client
  keepalives and server keepalives (`tcp_keepalives_idle=10`,
  `tcp_keepalives_interval=5`, `tcp_keepalives_count=3`), so Postgres drops the
  session and frees the lock about 25s after the holder's host goes away. The
  boot token is random per process, so 2 containers with the same hostname and
  pid still get different names, and the hostname is cut down to printable
  ASCII, which is all Postgres keeps.
- **Sessions are told apart by backend pid and start time.** The name is for
  people reading logs and for spotting a holder from this same host, never for
  deciding a session is ours.
- **Startup.** Nothing is ever terminated at startup. If the holder's name has
  this host in it, it's most likely this container's daphne from before
  supervisord restarted it, whose session Postgres hasn't dropped yet (the close
  never got there). The process tries the lock every second for up to 35s, past
  the 25s the keepalives take, before it settles for being a standby. A holder
  from another host means standby right away.
- **Heartbeat.** A thread runs `SELECT 1` on it every 30s. If the connection is
  gone it reconnects and takes the lock again. If the holder by then is the exact
  session it just lost (same backend pid and start time, ie Postgres hasn't
  noticed it's dead yet), that one session is terminated with
  `pg_terminate_backend()` and the lock is retried, for up to 60s. If anyone
  else has it the process logs CRITICAL and calls `os._exit(1)`, and supervisord
  starts it again as a standby.
- **Standby.** A process that doesn't get the lock starts no runtimes (MQTT,
  Z-Wave JS, the HA stream, control panels, the scheduler, the log broadcast
  worker). It still serves HTTP and websockets. It logs an ERROR naming the
  holder at startup and every 5 minutes after. Its heartbeat checks the holder
  every 30s, and once the lock is free it logs CRITICAL and exits so supervisord
  restarts it and it takes the lock. The runtimes only start from `ready()`, so
  a restart is the only way in. That's what gets a process that went standby
  behind a slow-to-drop session of its own running again, within about 30s of
  Postgres dropping it.
- **Door code pushes.** In a standby `push_task_running()` is true, so a door
  code save only queues the push (ADR-0111) and the active process's 5s tick
  sends it. A standby never makes a Z-Wave JS call from a request.
- **Startup errors.** If the database can't be reached when the lock is
  checked, it tries 5 times about 2s apart (each connect can take up to its 10s
  `connect_timeout`) and then raises `RuntimeLockUnavailable` from `ready()`, so
  daphne exits instead of serving without the lock, and supervisord restarts it
  until the database is back. That's a change from before, when daphne came up
  and the runtimes logged their own errors.
- **Forks.** `os.register_at_fork(after_in_child=...)` logs CRITICAL in a child
  forked from a process that has the connection, and the child keeps the
  inherited connection object referenced and never uses or closes it. Closing
  it would end the parent's session and free its lock.
- **Status.** `get_scheduler_status()["runtime_lock"]` and a `runtime` block in
  the system status payload report `active`, `held_elsewhere` (with the
  holder's `application_name`, backend pid and client address) or `disabled`
  (with the reason).
- **Setting.** `RUNTIME_LOCK=auto|off`. `auto` (the default) is on for Postgres
  and skipped on SQLite, where a second process can't share the database file
  over a network anyway. `off` skips it. Tests always run with it off unless a
  test turns it on.
- **Scheduler leader lock removed.** `SCHEDULER_LEADER_LOCK_ENABLED` and
  `SCHEDULER_LEADER_LOCK_ID` are gone. Setting either logs a deprecation
  warning. The scheduler is one of the runtimes, so the runtime lock already
  covers it.

Per-process state that's fine with one process, and stays that way:

| Where | What |
|-------|------|
| `CACHES` (locmem) | re-arm guard, throttles, HA leader key, connection caches |
| `CHANNEL_LAYERS` (in memory) | alarm state, system status, entity sync and log broadcasts |
| `alarm.signals` | `settings_profile_changed`, `alarm_state_change_committed` and the rest |
| `scheduler.runner` | task loops, wake events, `is_task_running`, `wake_task` |
| integration managers | MQTT client, Z-Wave JS client, HA stream, control panel listener and sync worker |

## Alternatives Considered

- **(a) Redis for everything.** A Redis or Valkey container for the cache,
  channels and pub/sub, plus one runtime lease. Real multi-worker, but a new
  container to run and back up, and about 8 to 10 PRs.
- **(b) One runtime process plus N stateless web workers.** The future path if
  more than one process is ever needed, see below. No new container, about 6 to
  8 PRs.
- **The scheduler leader lock as it was.** It only covered the scheduler, was off
  by default, and lost the lock silently when its connection dropped.
- **Exit a second process instead of serving HTTP.** Simpler, but a crash loop
  under supervisord is noisier than a standby that answers and says why.

### The future path, (b)

If we ever need more than one process, it's one runtime process (the one with
the lock) plus N web workers that never start runtimes, with Postgres as the bus
so there's still no new container.

- nginx sends everything to the runtime process by default and only an
  allowlist of read-only, stateless endpoints to the web workers.
- `django.core.cache.backends.db.DatabaseCache` for the keys that have to be
  shared (throttles, re-arm guard).
- Postgres LISTEN/NOTIFY for the in-process signals, which also covers #122.
  `settings_profile_changed` becomes a `Signal` subclass whose `send()` runs
  the local receivers and, in `transaction.on_commit`, calls
  `pg_notify('latchpoint_settings', '{"token", "profile_id", "reason"}')` with a
  fresh `uuid4` token it marks as seen. Every process runs a listener thread on
  its own dedicated connection (`LISTEN latchpoint_settings`), and on a token it
  hasn't seen calls `close_old_connections()` and replays the signal with
  `send_robust(..., remote=True)`. Every receiver only refreshes its own process
  and is idempotent, so a replay is safe. NOTIFY is only delivered on commit and
  is lost while a listener is disconnected, so a listener that reconnects
  replays one full refresh. The payload stays far under NOTIFY's 8000 byte cap.
  `alarm_state_change_committed` and the websocket broadcasts would go the same
  way, or move to a channel layer on top of it.
- The runtime lock stays as it is, it already makes sure only one process has
  the runtimes.

## Consequences

- Running a second process against the same database no longer doubles the
  runtimes, it gets a standby that serves HTTP and logs an ERROR every 5
  minutes.
- Requests a standby serves see that process's own cache, channel layer and
  signals, so its websocket clients don't get broadcasts from the active
  process, and its throttles are its own. It's a misconfiguration made safe,
  not a supported setup.
- A lost lock that someone else picks up restarts the process, so its open
  websockets drop and reconnect. So does a standby whose holder goes away, which
  means with 2 processes running, the standby takes over within about 30s of the
  active one dying. That's a side effect of the recovery above, not a supported
  hot spare.
- A daphne restart can take up to 35s longer to start the runtimes when its old
  session is still in Postgres.
- daphne won't start while the database is unreachable, it exits and
  supervisord keeps restarting it.
- The lock costs one extra Postgres connection per process and a `SELECT 1`
  every 30s.
- The gunicorn and uvicorn dependencies stay in `pyproject.toml`, but prod
  doesn't use them, it's daphne under supervisord.
- #162 stays open as the (b) epic, and #122 is closed under this decision.

## Related ADRs

- [ADR-0024](0024-in-process-task-scheduler.md): the in-process scheduler, whose leader lock this replaces.
- [ADR-0111](0111-door-code-push-off-the-request-path.md): queued door code pushes, which a standby now always uses.
