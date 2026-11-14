# ADR-0111: Door Code Pushes Are Queued for the Scheduler Instead of Made in the Request

**Status:** Accepted
**Date:** 2026-10-30
**Author:** Leonardo Merza

**Amends:** ADR-0092 §4 (the save pushes synchronously), ADR-0110 (create, update and Retry push in the request)

## Context

ADR-0092 §4 has the create, update and Retry requests push the code to each of
its locks before they return, with the scheduler's 300s task as the safety net.
Since #111 a push does a lot more than a `set`. It can read back an unconfirmed
slot, fetch the node's value ids, search for a free slot, send the `set`, read
the slot back up to 3 times with sleeps in between and send up to 7 CC 78
schedule calls. Each Z-Wave JS call can take its full 5s on a slow or asleep
lock, so one lock can take about 68s, and about 81s for a #193 resend. Locks are
pushed one after another, so a code on 2 slow locks can keep a request open
past nginx's 120s and get a 504 while the backend keeps going (issue #124).

An update also holds `lock_sync:` on every lock it touches for the whole
request (PR #157), pushes included, so every other push, clear or lock sync on
those locks waits behind the slowest one. Create and Retry only try the lock and
come back pending with "another sync in progress" while anything else has it.

PR #200 already fetches the value ids once per push, cancels a Z-Wave JS
command that times out and gives the request path's clears 5s.

## Decision

The request saves and returns, and a fast scheduler task makes the push.

- **Queue marker.** Migration `0011_assignment_push_requested` adds nullable
  `push_requested_at` and `push_requested_by` (SET_NULL) to
  `DoorCodeLockAssignment`. Additive, no backfill. `push_requested_by` has no
  DB foreign key constraint (`db_constraint=False`): code from before 0011
  doesn't know the column, so its user delete can't null it, and with a
  constraint deleting someone who queued a push on another user's code would
  fail. The id can dangle, and the task reads a user that's gone as no one, so
  the event falls back to the code's owner. `request_push(code,
  lock_entity_ids=None, *, actor_user=None)` stamps them on the locks
  `locks_to_push` picks (nothing for a code that's inactive, not started or
  expired), taking the code row first like every writer of a code's
  assignments. A lock an update adds to a code gets `push_requested_at` when
  its row is made, even on a code that's inactive or not started, so it's
  never taken for a lock a synced code was imported from (issue #222,
  ADR-0082). The task still only pushes it once the code belongs on its
  locks, and the stamp lapses like any other. A request is used up by the first push attempt on that lock
  that comes after it, the 300s retry and an inline push included, and lapses
  after `PUSH_REQUEST_TTL` (10 minutes), when the lock is the 300s retry's like
  any pending lock. Nothing clears the columns.
- **Wake.** `request_push` calls `scheduler.runner.wake_task` through
  `transaction.on_commit`, so a rollback never wakes anything. Each task loop
  waits on a wake event as well as its stop event. It's cleared right before
  the run, so a wake during a run gets one more run after it, and a wake during
  a failure backoff waits for the backoff. A wake in a process that doesn't run
  the task does nothing.
- **Task.** `push_requested_door_codes` runs every 5s (jitter 1s) behind a
  one-query `.exists()` gate (ADR-0103). It takes locks that are `pending`,
  need a `set` or a schedule, aren't being dropped, are under the cap, are on
  an active, started and unexpired code and have a live request no attempt
  came after, plus `locks_to_push`'s rule. Each lock waits up to 10s for its
  `lock_sync:` lock instead of try-lock-and-fail, is checked again once held,
  and is pushed with `push_requested_by` as the `code_synced` actor. A lock
  still busy after the wait stays queued for the next tick. So does a lock a
  door code save is waiting for, which the task doesn't take (issue #203). A
  save marks the locks it's still waiting for with a shared advisory lock the
  task looks for in `pg_locks`, before it tries a lock and again before every
  try while it waits for one, so a save behind a code's queued push waits for
  one lock's push instead of one per lock. A push already running is never cut
  short for it, and an added lock's reconcile gives way the same way. Nothing
  else does. The 300s `push_pending_door_codes` retry and
  `enforce_door_code_validity` still take a lock a save is waiting for, and the
  retry's pushes have no budget, so a save that lands behind one of them can
  still wait past its 45s and get a 409. A lock dropped
  while the task waited sends nothing (`PushSuperseded`) and the code's other
  locks carry on, unless the code itself is gone, off or out of its dates. Each
  code ends with `refresh_push_state`. A run that passes 600s is reported as
  stuck.
- **Budget.** A `BudgetedGateway` gives each lock's push 30s. Every call's
  timeout is cut to what's left, and once it's gone a call raises
  `TimeBudgetExceeded` without being sent. That takes the existing transient
  path: an unconfirmed attempt marker when the `set` went out, the lock left
  `pending`. A readback that answered empty before the budget ran out still
  says so (`LockCodeUnverified` with `read_back_empty`), so #193's empty-slot
  evidence is kept and the attempt isn't tagged `slot_available`. A queued or
  inline push that ran out of its budget isn't counted toward
  `door_codes.push_max_attempts`. Any other attempt from the queue counts like
  an inline one. When the budget runs out on the schedule right after the
  `set`, the lock is `schedule_pending` and its live request is stamped again,
  so the next tick sends only the schedule instead of leaving the PIN working
  around the clock until the 300s retry. A schedule-only push doesn't stamp it
  again, so that's one more try at most. Since issue #194 a push into a new
  slot also reads that slot once with CC 99 `get` before the `set`, since the
  value cache the slot is picked from can miss a keypad code. It comes out of
  the same 30s, so a lock that answers spends one more round trip, and one
  that doesn't answer it gets nothing sent. That's a counted transient failure
  like a `set` that timed out, so a lock that never answers reaches the cap,
  and sending the `set` anyway would queue it behind that `get` in the driver
  (issue #199). Running out of the budget on it isn't counted, like any other
  call the budget refuses.
- **Callers.** Create, update and Retry call `request_push` when
  `push_task_running()` says the task's loop is alive in this process, ie the
  thing `wake_task` reaches, or this process is a standby under the runtime
  lock (ADR-0112). Otherwise (`SCHEDULER_ENABLED=False`, tests) they push
  inline like before, with the same 30s per lock, and
  don't stamp anything. A DB error while queueing is logged and doesn't fail a
  save that already happened, and each pending lock with no error of its own
  says so in `last_push_error`. Any other error there is a bug, so it's raised
  in dev and tests like `PushInTransaction` (issue #203). Update still clears under its `lock_sync:` hold, but
  queues the push there and makes an inline one only after letting go. Retry
  keeps its checks, 409s, reset, re-arm and clear retries in the request,
  then queues the push. Its clear retries share a 15s budget, lock waits
  included, and a clear that doesn't fit keeps its `clear_failed` event for the
  scheduler. An inactive code's Retry, the not-started and expired branches,
  delete, retire and withdraw are unchanged. An off synced code's Retry runs
  the reconciles that take its PIN off its added locks (issue #221, ADR-0082)
  in the request, each with its 30s, since there's no push to queue.
- **API.** Each `lock_slot_assignments` entry gets `push_requested_at` and
  `push_queued` (issue #205). `push_queued` is the source of truth for whether
  the lock is queued. The server works it out with the task's own rule
  (`lock_push.push_queued`, ie `queued_push_assignments` plus `locks_to_push`)
  on the prefetched assignments, so it has the TTL, the cap and microsecond
  timestamps, none of which the browser can see. The frontend only falls back
  to comparing `push_requested_at` with `last_push_attempt_at` for an API that
  doesn't send it. The save response is always `pending` and the page polls
  for the outcome, fast only when the response has a lock with `push_queued`.

## Alternatives Considered

- **An in-process worker thread with a queue**, like the control panel sync
  worker. Lowest latency, but nothing watches it or restarts it, and a lost
  queue waits for the 300s tick.
- **Keep the push in the request with a budget.** The smallest change, but a
  lock that runs out of time waits 5 minutes for the next tick, and the update
  still holds every lock while it pushes.
- **Clear `push_requested_at` once the push is tried.** Explicit, but a
  request that comes in while an older one is being pushed has to be told
  apart from it, and the attempt time already says the same thing.

## Consequences

- A save no longer says whether the lock took the PIN. The card shows pending
  until the next poll, so the frontend has to poll faster after a save (the
  next PR).
- A queued push waits for its wake or the next 5s tick, which is a few seconds
  slower than the old inline push on a lock that answers.
- A process without the task still pushes in the request, now at most 30s per
  lock. A standby under the runtime lock (ADR-0112) doesn't, it only queues and
  the process with the lock sends the push on its next tick.
- A lock that runs out of its budget isn't counted for that attempt, and the
  request is spent after it, so the lock is the 300s retry's. That retry has no
  budget, so its attempts count and the cap still applies. A lock that times
  out on its first calls counts from the queue too.
- The idle tick adds one cheap query every 5s.
- The 30s per lock budget, the 10s lock wait, Retry's 15s clear budget and
  the 10 minute TTL are guesses, not timed on the Yales. So is update and
  delete's 45s lock wait, which is built on the 30s. Timing them needs QA on
  the real locks (issue #203).
- An inactive code's Retry still clears in the request without a budget, and
  so do update and delete.

## Related ADRs

- [ADR-0092](0092-zwavejs-lock-push-sync.md): push sync, its §4 amended here.
- [ADR-0103](0103-idle-scheduler-and-ingest-quiet-down.md): the idle gate the new task follows.
- [ADR-0110](0110-door-code-push-state-per-lock.md): per-lock push state, its request-path pushes amended here.
