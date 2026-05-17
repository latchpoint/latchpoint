# ADR 0092: Z-Wave JS Lock Push Sync — Programming PINs and Schedules to Physical Locks

## Status
**Proposed**

## Context

ADR 0068 introduced *pull*-sync (lock → LatchPoint) and explicitly deferred *push*-sync:

> "Combining read (pull) and write (push) sync in a single feature. Rejected because
> push-sync has different failure modes (lock may reject codes, slot capacity limits)
> and different security implications (accidentally overwriting lock codes). Better to
> ship pull-sync first, validate the model, then layer push-sync on top."
> — `docs/adr/0068-zwavejs-lock-config-sync.md:141`

Push-sync was never built. Operational hardening on pull-sync (ADRs 0069, 0081, 0082)
has since validated the data model. Meanwhile users discover the gap the hard way: in
prod on 2026-05-17, door code id=5 ("Watchers sophia") exists in the DB with
`source=manual`, `slot_index=NULL`, and a single `code_created` event — the PIN was
never sent to the Schlage front door lock. The keypad rejects the code because the
lock has no record of the slot.

The backend has exactly two runtime references to `CC_USER_CODE` (99):
`clear_lock_user_code_slot()` (synced-delete only, per ADR 0082) and the pull-sync
read loop. Zero calls to `method_name="set"`. The push direction simply does not exist.

### Relevant ADRs
- **ADR 0012** — Z-Wave JS Gateway + Connection Manager
- **ADR 0068** — Z-Wave JS Lock Config Sync (introduced pull-sync; deferred push)
- **ADR 0069** — Operational concerns for lock sync
- **ADR 0081** — Schedule Entry Lock — CC API Sync (introduced `invoke_cc_api`)
- **ADR 0082** — Lock domain + synced-code lifecycle + CC 99 `clear`

## Decision

### 1. New use case: `push_door_code_to_lock`

New module `backend/locks/use_cases/lock_push.py`, parallel to `lock_config_sync.py`.
Public signature:

```python
def push_door_code_to_lock(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 5.0,
) -> PushResult
```

Steps:

1. Resolve `node_id` via `_resolve_lock_node_id()` (reused from `lock_config_sync.py:628`).
2. Decrypt PIN via `SettingsEncryption.get().decrypt(door_code.encrypted_pin)`. Plaintext never leaves the function.
3. Enumerate `userIdStatus` per slot using the same pattern as `sync_lock_config` (`lock_config_sync.py:710-771`). Pick the **lowest slot where `_parse_user_code_status() == (False, None)`** (Available). Raise `LockSlotsFull` if none.
4. Acquire the per-lock advisory lock (`_try_acquire_sync_lock(lock_key=f"lock_push:{lock_entity_id}")`) to serialize concurrent pushes.
5. Call `zwavejs.invoke_cc_api(node_id, command_class=CC_USER_CODE, method_name="set", args=[slot, pin])`.
6. If the code has schedule fields (`days_of_week` AND `window_start` AND `window_end`):
   - Compute `(durationHour, durationMinute)` from start/end.
   - For each weekday bit set in `days_of_week`, call `zwavejs.invoke_cc_api(node_id, command_class=CC_SCHEDULE_ENTRY_LOCK, method_name="setDailyRepeatingSchedule", args=[{userId, slotId, startHour, startMinute, durationHour, durationMinute, weekdays: [<wd>]}])`. Same shape as the read at `lock_config_sync.py:486-606`, inverted.
7. On success:
   - `DoorCodeLockAssignment.slot_index = slot`, save.
   - `DoorCode.push_state = "pushed"`, save.
   - Emit `DoorCodeEvent(event_type=CODE_SYNCED, metadata={"action": "pushed", "slot_index": slot, "schedule_applied": <bool>})`.
   - Call `notify_entities_changed(source="lock_push", entity_ids=[lock_entity_id], changed_at=now)` (mirror `lock_config_sync.py:1094-1100`).

### 2. New field on `DoorCode`: `push_state`

Char field, three values:
- `pending` — saved in DB, push not yet attempted or queued for retry.
- `pushed` — last push succeeded; the lock has the current PIN + schedule.
- `failed` — push has hit the failure cap (permanent error or N retries exhausted).

Migration `locks/migrations/0006_door_code_push_state.py`:
- Default new column to `pending`.
- Backfill `synced` codes to `pushed` (the lock is authoritative).
- Backfill `manual` codes with non-NULL `slot_index` (none today, but defensive) to `pushed`; rest stay `pending`.

Also add `last_push_attempt_at` and `last_push_error` for operator diagnostics.

### 3. Trigger points

| Trigger | Use case | Push behavior |
|---|---|---|
| `POST /api/door-codes/` | `create_door_code()` | Push to each assigned lock. |
| `PATCH /api/door-codes/{id}` | `update_door_code()` | Re-push if PIN, `is_active`, or any schedule/window field changed. If `lock_entity_ids` shrinks, clear the dropped lock's slot via CC 99 `clear`. |
| `DELETE /api/door-codes/{id}` | `delete_door_code()` | Already clears for `synced` (ADR 0082); extend to clear for `manual` codes with non-NULL `slot_index`. |
| Scheduler tick | `push_pending_door_codes` | See section 4. |

`views/door_codes.py` POST/PATCH must wire `default_zwavejs_gateway` the same way
DELETE already does at line 110.

### 4. Save-now + scheduler retry

Failure-mode contract (the option ADR 0068 wanted us to design carefully):

- The use case calls `push_door_code_to_lock` **synchronously** with a 5s timeout.
- On success → DB row + assignment + `push_state=pushed` are committed atomically.
- On transient error (`GatewayTimeoutError`, `NodeAsleepError`, `GatewayUnreachableError`):
  - **DB row is still committed** with `push_state=pending` and `last_push_error` populated.
  - The scheduler task picks it up on the next tick.
- On terminal validation error (`LockSlotsFull`, malformed PIN): API returns 4xx before
  any DB write.
- On terminal gateway error (lock removed, node unknown): DB row saved with
  `push_state=failed`.

New scheduler task in `backend/locks/tasks.py`:

```python
@register(
    "push_pending_door_codes",
    schedule=Every(minutes=5),
    failure_backoff_base_seconds=60,
    failure_backoff_max_seconds=3600,
    description="Re-attempt programming pending door codes onto physical locks.",
)
def push_pending_door_codes() -> int: ...
```

For each `DoorCode` where `push_state="pending"` AND has at least one assignment with
no `slot_index`: attempt push. Cap consecutive failures via `SystemConfig` key
`door_codes.push_max_attempts` (default 24, i.e. ~2h with backoff). At the cap, flip
to `failed` and emit a `code_failed` event so operators see it.

Battery-powered locks: Z-Wave JS's Wake-Up Queue (WUQ) buffers commands for asleep
nodes. Most "asleep" cases succeed on the **first** synchronous attempt — ZJS returns
`ok` and the lock executes on next wakeup. The scheduler is the safety net for nodes
that are removed, dead-batteried, or have stopped responding entirely.

### 5. UI surfacing

Frontend (`frontend/src/features/doorCodes/`):
- Extend `DoorCodeSerializer` output: add `push_state`, `last_push_attempt_at`, `last_push_error`.
- List view: per-code badge — green "On lock (slot N)", yellow "Pending sync", red "Failed: <reason>" with a "Retry" button that calls a new `POST /api/door-codes/{id}/push/` endpoint (admin-only).
- No new form fields — slot is auto-picked.

### 6. Error taxonomy

In `backend/locks/use_cases/lock_push.py`:

```python
class LockSlotsFull(ValidationError):       # HTTP 409
class LockUnreachable(ConflictError):       # HTTP 409 (transient)
class LockPushFailed(GatewayError):         # HTTP 502
class InvalidPin(ValidationError):          # HTTP 400
```

The use case maps gateway exceptions:
- timeout / not-connected → `LockUnreachable` → DB committed, push enqueued.
- node unknown / lock removed → `LockPushFailed` → DB committed, `failed` state.
- PIN non-digit or length out of [4,8] → `InvalidPin` → 400 before any network call.

### 7. Security & encryption

- Plaintext PIN exists only inside `push_door_code_to_lock`. Pulled via
  `SettingsEncryption.get().decrypt()`, passed to `invoke_cc_api`, then drops out of
  scope.
- Logs and events never include PIN bytes. `last_push_error` stores only the exception
  class name + a sanitized message (e.g. `"Gateway timeout after 5.0s"`).
- `_normalize_pin`-style guards (`lock_config_sync.py:207`) validate format before the
  network call.

## Alternatives Considered

### Failure mode

| Approach | Pros | Cons | Decision |
|---|---|---|---|
| Fire-and-forget via WUQ only | Simplest | No operator visibility into "is it on the door yet?"; no recovery from lock removal | Rejected |
| Synchronous push, fail loud (no DB save) | Caller knows immediately | Save fails when lock is asleep; battery locks are asleep most of the time; hostile UX | Rejected |
| **Save now, retry via scheduler** | DB save always succeeds; clear operator visibility via `push_state`; reuses existing scheduler + backoff machinery (`scheduler/runner.py:61-89`); existing failure-tracking covers the retry telemetry | More moving parts; new field to migrate; scheduler task to register | **Chosen** |

### Schedule push scope

- **PIN only (MVP)** — rejected. UI already collects schedule fields; silently dropping
  them creates a divergence pull-sync will then re-import, surprising the user.
- **PIN + CC 78 daily-repeating** — chosen. The read path proves CC 78 works on the
  supported lock families.
- CC 78 weekday + year-day variants — out of scope; read path also only fully supports
  daily-repeating.

### Slot allocation

- User picks via UI — rejected. More UI, more rope, operators don't care.
- Auto + admin override — rejected as v1 scope creep; can layer later.
- **Auto-pick lowest free** — chosen. Mirrors how a human would do it from the keypad.

## Consequences

### Positive
- "Created in the UI = works on the door" closes the trust gap that prompted this ADR.
- Pull-sync stays the reconciliation backstop: if anyone programs the lock out-of-band
  (keypad, Z-Wave JS UI, HA service), pull-sync still imports it.
- Operator visibility via `push_state` — silent failure is the existing behaviour and
  the worst outcome.

### Negative / Risks
- The scheduler task becomes a new dependency for door codes to function end-to-end.
- Slot allocation races between concurrent pushes — mitigated by the per-lock advisory
  lock (`_try_acquire_sync_lock`, `lock_config_sync.py:108-126`).
- Permanently dead locks accumulate `pending` codes that retry forever — mitigated by
  the `door_codes.push_max_attempts` cap.
- Lock with full slots will reject new codes; UI must communicate this clearly via the
  `LockSlotsFull` 409.

### Migration / Backfill
- Existing `manual` codes (like id=5 "Watchers sophia") get `push_state="pending"`
  post-migration. The first scheduler tick attempts push — assuming the lock is
  reachable and has free slots, existing UI codes get synced for free.
- Existing `synced` codes get `push_state="pushed"` on migration — lock is the source
  of truth, no push needed.

## Out of Scope

- Multi-slot codes (one PIN occupying multiple slots).
- Per-code admin override of slot index.
- CC 78 weekday and year-day schedule variants (only daily-repeating is in scope).
- Notification-system surfacing of `code_failed` events — querying suffices for v1.
- Z-Wave JS-side WUQ inspection (e.g. "what's in the queue for node 109?").

## Verification

Backend (`backend/locks/tests/test_lock_push.py`):
- Mock `ZwavejsGateway.invoke_cc_api`; assert it's called with
  `command_class=99, method_name="set", args=[slot, pin]`.
- Assert `slot_index`, `push_state`, and `DoorCodeEvent` rows after success.
- Schedule-bearing code asserts `setDailyRepeatingSchedule` is called for each weekday
  bit with correct duration math.
- Transient gateway error → DB commits with `push_state=pending`.
- Slots-full → 409, no DB write.

Scheduler:
- Task registers and appears in `GET /api/scheduler/tasks/`.
- Backoff progression: 60s, 120s, 240s, ..., capped at 3600s.

End-to-end against prod Schlage:
- Create test code "ADR-0092 verify" via UI with PIN 12345.
- Assert `door_code_lock_assignments.slot_index IS NOT NULL` within 5s (lock awake) or
  5 minutes (queued via scheduler).
- Try the PIN on the door — keypad accepts; a `code_used` event lands within 30s.
- Delete the code; pull-sync confirms the slot is Available; assignment is removed.

## Open Questions (to resolve during implementation)

1. Is `setDailyRepeatingSchedule` exposed on every Schlage firmware Latchpoint
   currently supports? The read path falls back to weekday schedule if daily isn't
   available — does the write side need the same fallback? Investigate during impl.
2. Does the existing `default_zwavejs_gateway` raise distinguishable exception types
   for "node asleep with WUQ pending" vs "node unreachable"? If not, add a thin shim
   to surface that signal (the scheduler task needs it to size the backoff correctly).
