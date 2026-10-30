# ADR-0110: Door Code Push State Is Tracked Per Lock

**Status:** Accepted
**Date:** 2026-10-30
**Author:** Leonardo Merza

**Amends:** ADR-0092 (one `push_state` on the door code, the code-level attempt cap, the PIN and schedule pushed in one step), ADR-0109 (the validity task's `just_started` pass)

## Context

ADR-0092 keeps a door code's push outcome in one `push_state`, `last_push_error`
and `push_attempt_count` on `DoorCode`, whatever number of locks the code is on.
That one state has to say "this lock needs a human" and "that lock just timed
out" at once, and it can't. Since #111 a terminal failure on one lock makes the
whole code `failed`, and the scheduler only retried `pending` codes, so a second
lock that only timed out was never retried until someone hit Retry (issue #126).
The attempt cap was on the code too, so one lock landing zeroed the count of
another that kept failing.

ADR-0092 also sends the CC 99 `set` and the CC 78 schedule in one step. When the
`set` landed and the schedule didn't, the slot wasn't recorded, so the PIN
worked around the clock with nothing pointing at it (issue #123). PR #192 kept
that slot on record as an unconfirmed attempt, but the retry still had to read
it back and adopt it, and nothing said the schedule was what was missing.

Migrations `0009_assignment_push_state` and `0010_backfill_assignment_push_state`
(PR #195) added `push_state`, `push_attempt_count`, `last_push_attempt_at`,
`last_push_error` and `schedule_pending` to `DoorCodeLockAssignment` and wrote
them alongside the code's fields. Nothing read them yet.

## Decision

Each lock's push state lives on its assignment, and the code-level fields are
a rollup of them that keeps the API compatible.

- **Invariants.** A lock is `pushed` when it holds a slot and its schedule isn't
  pending. A slot that isn't `pushed` has `schedule_pending`. `pending` with no
  slot needs a `set`. `normalize_assignment_push_state` repairs rows that drift
  from these at the start of every scheduler tick, which a rollback to code
  that doesn't write the columns and a roll forward can cause. A `failed` lock
  on an active code whose own state isn't `failed` is stale there and is
  re-derived from the code.
- **One rollup writer.** `refresh_push_state` works out the code-level
  `push_state` and `last_push_error` from the locks and the clear failures and
  is the only writer of them. With no locks and nothing to clear an active code
  is `pending` and an inactive one `pushed`. An inactive code, or an active one
  before its start, is `pending` while a slot may still hold its PIN, else
  `pushed` when inactive and `pending` when scheduled. An active started code
  is `failed` when any lock is `failed` ("needs a human" wins, even while
  another lock is still retrying), else `pending` while a lock needs its `set`
  or schedule or a clear failure is outstanding, else `pushed`. A lock being
  dropped whose clear hasn't worked doesn't count. The error leads with the
  slots that may still hold the PIN, then has `lock.x: <error>` per lock. It
  takes the code row first, and every writer of a code and its assignments
  takes the code row first, `_delete_door_code_locked` included.
- **Caps.** The push cap (`door_codes.push_max_attempts`) is per lock. A sweep
  that runs every tick fails each lock still waiting on a push whose own count
  reached it, for codes that are active, started and not expired at the tick's
  `now`. The clear-retry cap stays on the code, and the code-level
  `push_attempt_count` counts clear retries only. A terminal failure counts an
  attempt on the lock too.
- **Scheduler.** A code is picked up when one of its locks is `pending` with no
  slot or a pending schedule and under the cap, whatever the code's own state,
  or when it has a clear failure and its clear-retry count is under the cap.
  `failed` locks are skipped.
- **Two-step push.** Once the PIN is confirmed the slot is recorded with
  `schedule_pending` when the code has days, and the schedule goes out after.
  A schedule that lands marks the lock `pushed`. A transient failure leaves it
  `pending` with the slot, and a terminal one `failed` with the slot, so a
  delete or deactivate still clears it. A lock with `schedule_pending` gets
  only the schedule next time, no CC 99 `set`. PR #190's marker, final
  transaction and `IntegrityError` handling stay, and that error now fails only
  the lock it happened on.
- **Retry.** Still one button per code. It re-arms every `failed` lock and every
  `pending` lock at the cap, resets the clear-retry count and pushes with
  `include_failed`. ADR-0109's not-started and expired branches stay.
- **Validity task.** `just_started` picks a code with a lock still waiting for
  its `set` or schedule, and re-arms its `failed` locks first. Before its start
  nothing pushes a code, so a lock is only `failed` then because the 0010
  backfill copied the code's failure onto it, and the code still goes on its
  locks at its start.
- **API.** Each `lock_slot_assignments` entry gets `push_state`,
  `last_push_error`, `last_push_attempt_at`, `push_attempt_count` and
  `schedule_pending`. Never a PIN. The code-level fields are the rollup.
- **No migration.** The columns and the backfill are 0009 and 0010.

## Alternatives Considered

- **Keep one state and retry `failed` codes that still have a lock that only
  timed out.** No migration, but the scheduler would have to work out from
  events which lock failed how, and the attempt cap would still be shared.
- **A per-lock Retry endpoint.** More control, but the card already has one
  Retry and the failures that need a human are rare. Retry re-arms every
  failed lock instead.
- **Let a pending lock win the rollup.** The code would show "Pending sync"
  while a lock is rejecting the PIN, which hides the one problem someone has to
  act on.

## Consequences

- A code can be `failed` while another of its locks is still being retried, so
  the badge needs to say both. That's the frontend change after this one.
- A lock the cap failed can have no error of its own (a busy lock, a push that
  was superseded), so the code says "Push gave up after N attempts" for it.
- The rollup is recomputed after every push, clear and edit, which costs a few
  queries each time. It reads the clear failures from events like before.
- A start moved within the past to after the code's last push attempt makes the
  validity task re-arm that code's failed locks once, like a Retry.
- `last_push_attempt_at` on assignments is NULL for rows from the backfill and
  from lock sync.

## Related ADRs

- [ADR-0092](0092-zwavejs-lock-push-sync.md): push sync, amended here.
- [ADR-0109](0109-door-code-validity-on-the-lock.md): door code validity on the lock, its `just_started` pass amended here.
