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
  use count) only, never at `code_type` or `source`, because lock syncs before
  #166 turned temporary manual codes into permanent synced ones that kept their dates.
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
  synced code keeps ADR-0082's rule, and the PIN, schedule and max uses stay
  read-only on all of them. Their locks can be added and removed (ADR-0082),
  and a dated synced code on more than one lock is retired off all of them.
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
- A synced code that lock sync turns off (its slot on the lock it was imported
  from read empty or disabled) comes off the locks someone added to it too
  (issue #221, ADR-0082), but only after two live reads of that slot confirm
  it. Clearing on the cache read alone would let a stale value cache on the
  first lock wipe a code that works on the others, so until the slot is
  confirmed the code stays on, and its PIN with it. Once it is, the added
  locks are flagged and their reconcile takes the PIN off them with #223's
  read first, so a PIN someone typed into one of those slots stays. Turning it
  back on at the import lock (enabling the slot) puts it back on them. A code
  turned off that way before this change, or one whose off wasn't confirmed,
  keeps its PIN on the added locks like before until a sync of the import lock
  confirms it, and the added locks still flagged for a new PIN or schedule
  wait for it to be back on (issue #220). Deleting the code still clears them
  right away.
  Removing the lock it was imported from makes it a manual code (issue #222,
  ADR-0082), and a manual code that's off has its PIN taken off its locks by
  the #167 inactive clear, so the added locks stop opening then too. That's on
  purpose: removing the import lock is a deliberate choice, and an off manual
  code doesn't stay on a lock. Turning it back on pushes it again.
- Synced codes with dates are retired too, which clears their slot on the
  lock. A synced code without dates is only touched when it's a stranded copy
  of a code being retired (issue #185, PR #211 review). That's an active
  synced code with no `end_at` holding the retiring code's exact PIN in a slot
  on one of its locks, where a push of the retiring code landed in that exact
  slot (a `code_synced` event with `action=pushed` and that `slot_index`) and
  the copy's row was created after the first of those pushes. A lock sync
  having recorded the two as duplicates of each other doesn't count. Event
  retention keeps each active code with an `end_at`'s first push per lock and
  slot so that event is still there at the retire (issue #212). With no push
  event left for the slot anyway (pruned before #212, or while the code was off
  or had no `end_at`) the copy is only flagged.
  A synced code latchpoint has pushed to any of its locks, ie one someone added
  a lock to (ADR-0082), is never a stranded copy either, since it's in use on
  purpose and its row's age says nothing about a slot latchpoint pushed it
  into. That's a push attempt or a queued push on any of its assignments, with
  or without a slot, which lock sync never stamps. It's broad on purpose,
  since leaving a code alone only means flagging it: it also counts a push to
  an added lock that failed with no slot, a dated synced code turned back on
  from latchpoint, and a row without a slot that migration 0010 stamped with
  its code's last attempt. It's checked again under the copy's `lock_sync:`
  locks before it's turned off, so a lock added after the retire looked is
  still seen. It's only flagged, and a pending retire of a copy someone has
  added a lock to since ends with `outcome=left_alone` and the flag.
  A stranded copy is turned off through the same locked deactivate, which clears
  its slot, and if that raises it's tried again on each later validity tick
  (`duplicate_retire_pending` until `duplicate_retire_done`), up to
  `door_codes.push_max_attempts` tries counting the retire's own, then one
  `max_attempts_exceeded` event. A retry that finds the copy deleted ends with
  `outcome=gone`, and one that finds it off, dated or holding another PIN with
  `outcome=changed` (issue #212). Event retention keeps the pending event
  while it's pending. Every other synced code with the PIN is left alone and
  flagged with a
  `duplicate_pin_survives_retire` event on the retiring code (the copy's id,
  lock and slot, never the PIN) and a warning, since it may be someone's own
  keypad code that happens to share the PIN.
- A synced code with an `end_at` that lock sync turned off can be turned back
  on from latchpoint too, since the row looks the same as a retired one. That
  puts its PIN back on the lock. Lock sync turns a synced code off when its
  slot reads empty, and also when it reads Occupied/Disabled, so turning one of
  those on from latchpoint overrides a disable done at the lock (issue #189).

## Related ADRs

- [ADR-0068](0068-zwavejs-lock-config-sync.md): lock config sync, which turned manual codes into synced ones before #166.
- [ADR-0082](0082-zwavejs-lock-domain-and-synced-code-lifecycle.md): synced code lifecycle and CC 99 clear, its read-only rule amended here.
- [ADR-0092](0092-zwavejs-lock-push-sync.md): push sync, amended here.
