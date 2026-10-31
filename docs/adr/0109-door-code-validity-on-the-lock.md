# ADR-0109: Door Code Start and End Dates Are Enforced by Adding and Removing the PIN

**Status:** Accepted
**Date:** 2026-10-29
**Author:** Leonardo Merza

**Amends:** ADR-0092 (`start_at` and `end_at` left out of the push), ADR-0082 (synced codes read-only except `label`)

## Context

ADR-0092 programs a door code's PIN and its CC 78 daily window onto the lock. It
never programs `start_at` or `end_at`. The push trigger fields left them out on
purpose, with the comment that they are "validity-window fields enforced in
software, never programmed onto the lock".

Nothing enforced them in software either. The lock is what decides whether a
PIN opens the door, and latchpoint never sees a keypad entry before the lock
accepts it. So a temporary or one-time code kept working on the door after its
`end_at` until someone turned it off by hand, and a code with a future
`start_at` was pushed the moment it was saved and worked before it started
(issue #145). `max_uses` has the same problem, since nothing counts door code
uses yet.

## Decision

The PIN is only on a lock between `start_at` (inclusive) and `end_at`
(exclusive). Latchpoint enforces that by putting the PIN on and taking it off
at those times, through the same push and clear paths ADR-0092 and the fixes
after it (#144, #157, #167) already use.

- **Shared predicates.** `locks/use_cases/code_lifecycle.py` has `is_started`,
  `is_expired`, `is_exhausted` and `validity`. They look at the dates (and the
  use count) only, never at `code_type` or `source`, because lock sync can turn
  a temporary manual code into a permanent synced one that keeps its dates.
- **Never push outside the window.** `push_door_code_to_assigned_locks` returns
  without pushing for a code that hasn't started or has expired, and
  `push_door_code_to_lock` raises `PushSuperseded` when it finds that under the
  `lock_sync:` lock. `push_pending_door_codes` only retries pushes for codes in
  their window (clear retries still run for everything). Retry on an active
  code that hasn't started only retries and withdraws the clears it still has
  outstanding, without pushing it, and answers 409 when there are none. Retry
  on an active code past `end_at` retires it straight away.
- **`start_at` crossing now is a push trigger.** An update that moves
  `start_at` into the future clears the code off its locks like a schedule
  change does, and one that moves it into the past pushes it. Moving it within
  the past or within the future touches nothing.
- **Expiry is a deactivate.** `retire_door_code` takes the `lock_sync:` locks
  the way an update does, reads the row again, checks it's still expired and
  runs the normal locked update with `is_active: false` and `reason` in the
  event. To the clear machinery it is a user turning the code off, so failed
  clears are retried, capped and settled the way #144 and #167 already do.
  Extending `end_at` on an expired code doesn't turn it back on. The user
  turns it on again, and the API refuses that while the code would still be
  expired.
- **One scheduler task, every 60s.** `enforce_door_code_validity` retires
  active codes past `end_at`, clears active codes before `start_at` that still
  hold a slot (codes pushed before this ADR), and pushes codes whose `start_at`
  has passed and that haven't had a push attempt since. It catches errors per
  code, a busy lock included, and never raises.
- **API.** `end_at` must be after `start_at`, and in the future on create or
  when an update changes it. An update's `start_at` or `end_at` that's the
  stored one exactly, or the stored one cut to the minute (the edit form drops
  the seconds), counts as unchanged and isn't written, so the stored seconds
  stay. Any other value is a change, a same-minute one with seconds included,
  so an API client can still move a date by seconds (issue #189). The order
  check only runs when an update changes a date, so an unrelated edit on an
  older row with equal dates still saves, and it checks both the dates that
  were sent and the ones that end up stored. `is_active: true` is refused while
  the code would be expired, and the serializer adds `validity` (`scheduled`,
  `valid`, `expired`, `exhausted`).
- **Synced codes with an end date.** ADR-0082 makes every field but `label`
  read-only on a synced code. A synced code that has an `end_at` (the only kind
  the scheduler turns off) can also set `is_active`, `start_at` and `end_at`,
  with the rules above, whether it's on or off, and the `code_type` check for a
  time range is skipped for it since lock sync sets that from the lock's
  schedule but keeps the dates. Turning it on goes through the normal push, and
  the next lock sync finds its PIN in the slot it's tracked in, so it stays on
  and nothing is imported. Once it's on it can be turned off or have its window
  fixed the same way, ie while it's only waiting on its start (issue #189). Its
  `end_at` can be moved but not cleared, since without one it would drop out of
  this rule and be stuck however it was left. It's keyed on the row rather than
  on the retire event because event retention deletes old events. Every other
  synced code keeps ADR-0082's rule, and the PIN, schedule, max uses and locks
  stay read-only on all of them.
- **No migration.** The first tick after deploy retires codes already past
  `end_at` and clears codes pushed before their start.

`max_uses` stays stored and accepted by the API but the UI hides it, since
nothing counts uses yet. Counting uses from Z-Wave JS access control
notifications and retiring used up codes is a separate change.

## Alternatives Considered

- **Program the dates onto the lock with CC 78 year-day schedules.** The lock
  would enforce them without latchpoint running, but it needs the lock's clock
  set, can't be combined with the daily schedules we already push on the
  locks we have, and it isn't known whether the Yale YRD430 supports it. Kept
  as a later backstop for codes without `days_of_week`, behind a capability
  check.
- **Check the dates when a keypad entry is reported.** The lock has already
  opened the door by then, so it can't stop an expired code.
- **Hotfix only the expiry.** Leaves codes with a future start working early
  and would need the same locking and retry work again for the start.

## Consequences

- A code can stay on its locks for up to about a minute past `end_at`, plus
  however long the lock takes to answer the clear. A lock that's offline at
  expiry keeps the PIN until a retried clear reaches it, and the code shows
  pending with that lock and slot in its error the whole time.
- A scheduled code goes on its locks up to a minute after `start_at`.
- A scheduled code's withdraw clear that keeps failing hits the attempt cap
  like any other clear. Retry then tries those clears again and takes off
  anything else it still holds, so the PIN doesn't keep working until its
  start.
- A push that's already running when `end_at` passes can still land, since it
  only checks the dates once it holds the lock. The next tick retires the code
  and clears it.
- `exhausted` is reported in `validity` but nothing enforces it until use
  counting lands in PR2, so a used up code stays on its locks.
- Latchpoint has to be running for codes to start and expire on time.
- Synced codes with dates are retired too, which clears their slot on the
  lock. A synced code without dates is only touched when it's a stranded copy
  of a code being retired (issue #185, PR #211 review). That's an active
  synced code with no `end_at` holding the retiring code's exact PIN in a slot
  on one of its locks, where a push of the retiring code landed in that exact
  slot (a `code_synced` event with `action=pushed` and that `slot_index`) and
  the copy's row was created after the first of those pushes. A lock sync
  having recorded the two as duplicates of each other doesn't count, and with
  no push event left for the slot (event retention) the copy is only flagged.
  Such a copy is turned off through the same locked deactivate, which clears
  its slot, and if that raises it's tried again on each later validity tick
  (`duplicate_retire_pending` until `duplicate_retire_done`), up to
  `door_codes.push_max_attempts` tries, then one `max_attempts_exceeded`
  event. Event retention keeps the pending event while it's pending. Every other
  synced code with the PIN is left alone and flagged with a
  `duplicate_pin_survives_retire` event on the retiring code (the copy's id,
  lock and slot, never the PIN) and a warning, since it may be someone's own
  keypad code that happens to share the PIN.
- A synced code with an `end_at` that lock sync turned off can be turned back
  on from latchpoint too, since the row looks the same as a retired one. That
  puts its PIN back on the lock. Lock sync turns a synced code off when its
  slot reads empty, and also when it reads Occupied/Disabled, so turning one of
  those on from latchpoint overrides a disable done at the lock (issue #189).

## Related ADRs

- [ADR-0068](0068-zwavejs-lock-config-sync.md): lock config sync, which can turn manual codes into synced ones.
- [ADR-0082](0082-zwavejs-lock-domain-and-synced-code-lifecycle.md): synced code lifecycle and CC 99 clear, its read-only rule amended here.
- [ADR-0092](0092-zwavejs-lock-push-sync.md): push sync, amended here.
