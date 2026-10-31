# ADR-0114: Door Code Uses Are Counted from Z-Wave JS Keypad Unlocks

**Status:** Accepted
**Date:** 2026-10-31
**Author:** Leonardo Merza

**Amends:** ADR-0109 (`exhausted` reported but nothing counts uses)

## Context

ADR-0109 takes a door code's PIN off its locks at `end_at`, but `max_uses` and
one-time codes still don't limit anything, because nothing counts a use
(issue #145). `uses_count`, `last_used_at` and `last_used_lock` were only ever
written by `record_door_code_usage`, which had no callers, so production has no
`code_used` door code events at all.

The lock decides whether a PIN opens the door, so latchpoint can only count a
use after the fact. Z-Wave locks report it with a Notification CC (113) Access
Control (type 6) event. Event 6 is a keypad unlock and event 34 the newer
credential unlock. Event 5 is a keypad *lock*. `args.parameters.userId` is the
CC 99 slot the code was typed from. The Z-Wave JS bridge already hands these to
its listeners, but nothing in `locks` listened.

It isn't verified yet whether the Yale YRD430-F-ZW3 (fw 2.40.0) sends `userId`
(older Yales only sent the V1 alarmType 19 / alarmLevel compat), or whether it
sends one unlock twice.

## Decision

Count uses from those events on the existing bridge, and only count. Turning a
used up code off is the next change.

- **Parser.** `locks/keypad_events.py` `parse_keypad_unlock` is pure. It
  returns `KeypadUnlock(node_id, slot, event)` only for ccId 113, type 6, event
  6 or 34 and a `parameters.userId` that's an int of 1 or more.
- **Listener.** `locks/runtime.py` registers on the bridge from
  `LocksConfig.ready()` behind `should_start_runtimes`, so only the process with
  the runtime lock counts (ADR-0112). On the `zwavejs-events` thread it only
  parses, logs every CC 113 event at INFO (`zwavejs keypad event ...`, through
  the manager's sanitizer) and queues keypad unlocks. Counting takes the code
  row with `select_for_update`, which can wait on a push or lock sync holding
  it, so it runs on its own `locks-keypad-uses` thread and the events thread
  that also carries Ring keypad codes never waits on it (ADR-0100). No Z-Wave
  I/O on either thread.
- **Mapping.** The node's entities (`attributes.zwavejs.node_id`, on the
  gateway's home id or with none recorded) give the locks, and an assignment on
  one of them with `slot_index == userId` gives the code. No assignment falls
  back to a code whose clear of that slot is still outstanding. More than one
  match is logged and skipped.
- **Counting.** `locks/use_cases/code_usage.py` `record_keypad_use` runs in one
  transaction. It takes the code row first, like every writer of a code, checks
  the code still has the slot (or a clear of it outstanding), dedupes against a
  `code_used` event on the same lock and slot in the last 10s, then runs
  `uses_count = F("uses_count") + 1` with `last_used_at` and `last_used_lock`
  and writes a `code_used` event with `slot_index`, `source: "zwavejs"`,
  `notification_event`, `uses_count`, `max_uses` and `over_limit`. Uses are one
  total across all of a code's locks.
- **Not counted, still recorded.** A slot no code has is a `code_used` event
  with no code and `unmatched`, the lock and the slot. A slot that may still
  hold an older PIN (an unresolved clear) or a code that's off is a `code_used`
  event on the code with `stale_slot` and `stale_reason`, and doesn't count.
- **Updates keep the count.** `_save_unless_deleted` writes every field but
  `uses_count`, `last_used_at` and `last_used_lock` and reads those back, so an
  update that read the code before a use landed doesn't put the old count back.
- **Logs.** The event log sanitizer also hides `args.parameters.userCode`, and
  raw (Buffer) parameters whole, so the INFO line never has the PIN.
- **Dead code.** `locks/use_cases/code_validation.py` (`validate_door_code`,
  `record_door_code_usage`) and its tests are gone.

## Alternatives Considered

- **Poll the Door Lock Logging CC.** The Yales probably don't support it and
  polling drains the battery.
- **HA `zwave_js_notification` events.** Another hop and another connection to
  keep up. Could backfill a missed use later, not the main path.
- **Count on the `zwavejs-events` thread.** It's DB only, but the row lock can
  wait behind a push and that thread also carries the Ring keypad's codes.

## Consequences

- If the YRD430 doesn't send `userId`, nothing counts. The INFO log of every
  CC 113 event for the first week is there to find that out, along with HA
  Developer Tools > Events > `zwave_js_notification`. A V1 alarmType 19
  fallback would be a follow-up.
- Events aren't replayed, so a use while latchpoint is down or disconnected
  from Z-Wave JS isn't counted.
- Two real uses of the same slot on the same lock within 10s count once.
- A slot only known from an unconfirmed push attempt (no `slot_index` yet)
  records an unmatched use.
- The INFO log also has CC 113 events from other devices, ie sensors that
  report through the Notification CC.
- A used up code keeps working. The next change retires it through
  `enforce_door_code_validity` and shows the limit in the UI.

## Related ADRs

- [ADR-0100](0100-control-panel-reconciling-sync-worker.md): no blocking work on the `zwavejs-events` thread.
- [ADR-0109](0109-door-code-validity-on-the-lock.md): start and end dates, amended here.
- [ADR-0112](0112-one-runtime-process-per-database.md): only the process with the runtime lock starts the listener.
