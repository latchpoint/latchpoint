# ADR 0082: Z-Wave JS Lock Domain Assignment, Synced Code Read-Only Enforcement, and Physical Code Deletion

## Status
**Implemented**

## Context

ADR 0068 introduced lock config sync — pulling user codes (CC 99) and schedules from Z-Wave JS locks into LatchPoint `DoorCode` rows. ADR 0081 added `invoke_cc_api` to the gateway and daily repeating schedule sync via CC API fallback. Several operational gaps remained:

### 1. Lock entities have no distinguished domain

During Z-Wave JS entity sync, all entities are assigned a domain inferred from their value type (`sensor`, `binary_sensor`). A lock node with CC 98/99/78 produces dozens of entities (one per slot, per status, per schedule) — all typed as `sensor`. The lock config sync page and future lock-centric UI need a single canonical `domain="lock"` entity per node to query against.

### 2. Synced door codes are fully editable

When a door code is imported via `sync_lock_config`, its source is set to `DoorCode.Source.SYNCED`, indicating the physical lock is the authoritative source for that code's PIN, schedule, and active/inactive status. However, the update endpoint allows editing all fields — including `code`, `is_active`, `start_at`, `end_at`, `days_of_week`, `window_start`, `window_end`, `max_uses`, and `lock_entity_ids`. Editing these fields on a synced code creates a divergence between LatchPoint and the physical lock with no mechanism to push changes back to hardware.

### 3. Deleting a synced code does not clear the physical lock slot

Per ADR 0068, deleting a synced code "dismisses" it — marking the assignment `sync_dismissed=True` and setting `is_active=False`, while leaving the physical lock slot occupied. This was an intentional design choice when the system was pull-only. With `invoke_cc_api` now available (ADR 0081), we can clear the slot on the physical lock during deletion.

### Relevant ADRs
- **ADR 0012** — Z-Wave JS Gateway + Connection Manager
- **ADR 0068** — Z-Wave JS Lock Config Sync (Codes & Schedules)
- **ADR 0069** — Lock Config Sync: Operational, Security & UX Concerns
- **ADR 0081** — Schedule Entry Lock — CC API Sync (introduced `invoke_cc_api`)

## Decision

### 1. Assign `domain="lock"` to a representative entity per lock node during entity sync

During `sync_entities_from_zwavejs()`, after collecting a node's value IDs, select a single representative lock value ID using priority ordering:

1. CC 98 (`Door Lock`) with `property="currentMode"` — highest priority (the most meaningful lock state)
2. Any other CC 98 value ID
3. Any CC 99 (`User Code`) value ID
4. Any CC 78 (`Schedule Entry Lock`) value ID

The selected entity gets `domain="lock"` and a simplified name (just the node name, without the value label suffix). All other entities on the same node retain their inferred domain. This entity is exempt from the `per_node_limit` cap to guarantee it is always synced.

**Lock command class constants** (`CC_DOOR_LOCK=98`, `CC_USER_CODE=99`, `CC_SCHEDULE_ENTRY_LOCK=78`, `LOCK_COMMAND_CLASSES`) are defined in `integrations_zwavejs/manager.py` and imported by the entity sync module.

### 2. Enforce read-only editing for synced door codes (label and locks only)

`DoorCodeUpdateSerializer` rejects updates to all fields except `label` and the code's locks when the code's source is `SYNCED`. The rejected fields are:

- `code` (PIN)
- `is_active`
- `start_at`, `end_at`
- `days_of_week`
- `window_start`, `window_end`
- `max_uses`

`lock_entity_ids` was on this list until synced codes' locks were made editable (below).

This validation is applied at the serializer level, so the use-case layer doesn't need to know about source-based restrictions. The user can still rename a synced code's label for organizational purposes.

**Synced codes' locks are editable.** `lock_entity_ids` is no longer read-only, and neither are `add_lock_entity_ids` and `remove_lock_entity_ids` (issue #159). A synced code's locks are added and removed the same way a manual code's are: latchpoint pushes the code's PIN into a free slot on an added lock through the queued push (ADR-0111) and tracks that slot on the code's assignment, and clears the slot on a removed lock through the normal clear and pending removal path, including the lock the code was imported from. The code stays `source=synced`. The PIN, the schedule (`days_of_week`, `window_start`, `window_end`) and `max_uses` still come from the lock and stay read-only, and `is_active`, `start_at` and `end_at` only open up under ADR-0109's rule for synced codes with an `end_at`. The real case is a master code imported from the Front Door that also has to open the Back Door.

- A synced code imported from a lock that masks its codes has no stored PIN, so adding a lock to it is a 400 ("Latchpoint doesn't have a readable PIN for this code, so it can't put it on another lock."), and so is one whose stored PIN can't be decrypted. Removing one still works, since a clear doesn't need the PIN.
- Adding a lock is refused with a 409 when another code already has the PIN on that lock, the same check turning a code on uses (issue #188), against the added locks only. That goes for active manual codes too.
- Removals that would leave a synced code with no locks are a 400, a full `lock_entity_ids: []` included, since the door codes list leaves out a synced code with no locks.
- Lock sync treats the pushed slot as the code's own, since the code tracks it: it isn't imported as a "Slot N" code and the code isn't flagged `duplicate_pin` against itself. A slot latchpoint pushed (its assignment holds a slot and has a push attempt, which lock sync never stamps) gets the manual code rule from issue #166. When it's occupied, lock sync only marks that lock pushed and flags a disabled slot, skips it as `pin_mismatch` when it holds another PIN, and never takes the code's PIN, active flag, schedule or owner from it, whether the code is on or off. When the value cache calls it Available it's only let go after a live readback answers empty twice, then pushed again, and the code is never turned off for it. The slot on the lock the code was imported from keeps the synced rule above, so that lock alone decides the code's PIN, schedule, owner and active flag. A code it turns off keeps its PIN on the added locks (ADR-0109).
- A new PIN or schedule lock sync takes from the lock the code was imported from goes on to the added locks, the way an edit goes out to a manual code's locks (issue #220). The sync holds only that lock's `lock_sync:` lock, so it sends nothing itself and queues it all.
  - A new PIN, or a schedule that drops a day or goes away, queues a clear of the code's slot on each added lock with the PIN it holds and wakes `push_pending_door_codes` once the sync commits. The scheduled clear is a `clear_failed` marked `planned` and `repush`, recorded as a `code_updated` event, and the code reads "Waiting to clear slot N on X before sending the new PIN" (or schedule) until it's tried. Only a clear that then fails logs a `code_failed`.
  - The scheduler reads that slot back first. It's cleared when it still holds that PIN, or a code the lock won't show, and the code is pushed again. A slot holding a PIN latchpoint never set there (typed in at the keypad, the `pin_mismatch` case) isn't cleared: latchpoint lets go of it and pushes the code into a free slot.
  - A schedule that keeps every day it had, including a first schedule on a code that had none, sets `schedule_pending` on the added lock and queues the push (ADR-0111), which sends only the schedule into the slot the code has there.
  - An added lock with no slot yet gets the current PIN and schedule from its pending push, and slots an unconfirmed push may have left the old PIN in are queued for a clear that reads them back first.
  - A code that's off keeps its PIN and window on the added locks (ADR-0109). The queued clear waits until it's back on, then the change goes out. A delete still clears them.
- A push that's running when a sync of the import lock changes the code reads the code again under its row lock before it commits the slot. When the PIN it sent isn't the code's PIN any more, the slot is kept on record with a queued clear of the PIN it sent, and the code is pushed again after it, instead of being marked pushed with the old PIN. A schedule-only push whose schedule changed meanwhile keeps `schedule_pending` and queues itself again, or queues the clear when the new schedule dropped a day.
- A new PIN is only taken from the lock the code was imported from, and so only sent on, when a live CC 99 `get` of the slot reports it. A new schedule, one removed included, is only taken when a live CC 78 read of the slot's daily repeating entries gives it, unless the sync's schedule read was live already (a lock with no CC 78 values in the cache). A value only the cache has (stale, or cached for a `set` the lock dropped) would take a working PIN or window off the added locks. Until a sync's readback confirms it, or when the read doesn't fit the sync's readback budget, the code keeps its PIN or schedule and the slot gets `pin_change_unconfirmed` or `schedule_change_unconfirmed`. A lock that masks its codes gives no PIN, so nothing changes and nothing is sent. Codes on that lock alone take a new PIN and schedule as before, without a readback.
- A queued clear on an added lock only holds back that lock's syncs. Every other clear still holds back the code's sync on every lock (PR #165), but this one only follows a change the import lock already made, so counting it there would stop the import lock deciding the code's PIN and active flag for good once the added lock's clear hit the retry cap.
- An added lock where another code already has the new PIN (in a slot, or active and waiting for its push, issue #188) still gets the old PIN cleared, since it was changed on purpose, but the code isn't pushed there. Once the slot is gone the lock is failed with "… already has this PIN in slot N as door code M, so this code is off that lock. Delete that code, then Retry.", and the sync's slot gets `pin_held_on_other_lock`.
- Adding a lock to a synced code is checked for another code with the PIN on that lock whether the code is on or off, since lock sync turns an undated one back on without that check.
- ADR-0109's stranded copy rule never retires a synced code latchpoint has pushed to a lock. It's only flagged.

**Manual codes stay latchpoint's (issue #166).** Latchpoint, not the lock, is the authority for a manual code, so lock config sync never turns one into a synced code. Only slots latchpoint doesn't know about are imported as synced. For a manual code in its own slot the sync leaves the PIN, schedule, owner and active flag alone and only marks that lock pushed, flags a slot the lock reports disabled, and lets go of a tracked slot only when a live readback answers it empty twice and the lock can't already have the PIN in another slot, so the scheduler pushes the code again. Codes an earlier sync converted stay synced.

### 3. Delete synced door code clears the physical lock slot via CC 99 API

When a synced door code is deleted, the system now clears the user code slot on the physical lock before dismissing the record in the database.

#### Flow

```
DELETE /api/door-codes/{id}  (admin + reauth)
  │
  ├─ code.source == SYNCED?
  │   ├─ For each assignment with a slot_index:
  │   │   └─ invoke_cc_api(node_id, CC_USER_CODE=99, "clear", [slot_index])
  │   │       ↳ Clears the slot (Z-Wave JS UserCodeCC.clear)
  │   │       ↳ Raises GatewayError if lock unreachable → HTTP 502, delete aborted
  │   │
  │   ├─ All clears succeeded:
  │   │   ├─ Create DoorCodeEvent(CODE_DELETED, metadata={cleared_from_lock: true})
  │   │   └─ Hard-delete code and assignments from DB
  │   │
  │   └─ Any clear failed:
  │       └─ Raise error, no DB changes (Option A: fail-fast)
  │
  └─ code.source == MANUAL?
      └─ Hard-delete code (existing behavior, unchanged)
```

#### Error handling: Option A (fail the delete)

If the Z-Wave JS server is unreachable or the lock doesn't respond, the `invoke_cc_api` call raises a `ZwavejsCommandError` (subclass of `GatewayError`), which the exception handler maps to HTTP 502. The database state is unchanged — the user must retry when the lock is reachable.

Some synced codes are deleted the way a manual code is instead: clears an earlier save couldn't finish are retried, a clear that fails is recorded for the scheduler's retries, unconfirmed push slots are read back and cleared, and when any of that can't be done the delete is refused with "The door code wasn't deleted and is now off", with the slots it did clear forgotten. That's a synced code latchpoint has ever pushed or queued a push of to any lock (an assignment with `last_push_attempt_at` or `push_requested_at`, which includes rows migration 0010 stamped from the code's last attempt and a dated synced code turned back on under ADR-0109), or one that still has a clear failure or an unconfirmed push attempt on record, on a lock it's on or one it was removed from (§2). Fail-fast there would leave the row saying a slot it already cleared is still held, with nothing recorded to retry, or delete the row along with the record of a slot only latchpoint knew about and leave the PIN in it. Every other synced code keeps the fail-fast. Retry on a refused synced code that's off answers 409 and says to delete it again once its locks respond, since an undated one can't be turned on from latchpoint.

**Rationale for Option A over alternatives:**

- **Option B** (dismiss + queue retry) adds background job complexity and risks "phantom" codes that appear deleted in the UI but persist on the lock indefinitely if retries exhaust.
- **Option C** (dismiss + warn) provides poor UX — the user thinks the code is deleted but must remember to manually clear the lock.
- **Option A** is simple, transparent, and ensures DB and lock stay in sync. The failure case (lock offline) is visible and actionable.

#### Idempotency

Clearing an already-empty slot via `clear(slot_index)` is safe — the lock accepts the command without error. This means retrying a failed-then-recovered delete operation is harmless even if some slots were cleared before the failure.

#### Gateway helper

A `clear_lock_user_code_slot()` function is added to `locks/use_cases/lock_config_sync.py`, co-located with `_resolve_lock_node_id()` and the existing CC 99 sync logic. It resolves the lock entity ID to a Z-Wave node ID and invokes `CC 99 clear(slot_index)`.

### 4. Door code lock picker filters to code-capable locks only

The door code create/edit UI previously displayed all entities with `domain="lock"` from all integrations — including Home Assistant car locks, Zigbee locks, and other non-Z-Wave locks that have no user code management capability. Only Z-Wave JS locks with CC 99 support can have codes managed programmatically. The lock picker now filters to only show code-capable locks.

#### Filtering logic

A shared utility (`features/doorCodes/utils/lockFilters.ts`) provides two functions:

- **`getZwavejsNodeId(entity)`** — extracts the Z-Wave JS node ID from `entity.attributes.zwavejs.nodeId` (or `node_id`), handling numeric and string coercion. Returns `null` for non-Z-Wave entities.
- **`isCodeCapableLock(entity)`** — returns `true` when `domain === "lock"` AND `getZwavejsNodeId()` returns a valid node ID. This is the single predicate used by `DoorCodesPage` to filter the lock list.

This is a frontend-only filter. All necessary metadata (`attributes.zwavejs.node_id`) is already present on `Entity` objects from the general entities endpoint — no new backend endpoint or query parameter needed.

#### Scope

| Context | Before | After |
|---------|--------|-------|
| Lock config sync card | Already Z-Wave-filtered (unchanged) | Unchanged — self-filters as belt-and-suspenders |
| Door code create form | All `domain="lock"` entities | `isCodeCapableLock` only |
| Door code edit form | All `domain="lock"` entities | `isCodeCapableLock` only |
| Lock name display on existing codes | All `domain="lock"` entities | Unchanged — `lockNameByEntityId` map remains unfiltered for backwards-compatible display |

The `lockNameByEntityId` lookup map (used to display names on existing door code cards) is intentionally *not* filtered. This ensures that codes historically assigned to non-Z-Wave locks still display their lock names correctly.

#### Extensibility

If a future integration (e.g., Matter, Z-Wave Long Range) adds user code management support, `isCodeCapableLock()` is the single extension point — add the new integration's capability check alongside the Z-Wave check.

## Consequences

### Positive
- Lock entities are discoverable by `domain="lock"` for UI rendering and lock-centric features
- Synced codes cannot silently diverge from physical lock state through edits
- Deleting a synced code is a real operation — the physical lock slot is cleared, not just hidden
- `clear_lock_user_code_slot()` is reusable for future features (e.g., bulk slot management, code rotation)
- Existing dismiss/undismiss mechanism is preserved as a fallback audit trail
- Door code lock picker only shows locks that actually support user codes — no car locks, Zigbee locks, or other non-code-capable devices cluttering the selection

### Negative
- Deleting a synced code now requires the lock to be online and reachable via Z-Wave JS
- CC API calls generate RF traffic to the lock during deletion (one call per lock assignment)
- Entity sync slightly increases logic complexity with the lock representative selection

### Risks
- Some lock firmwares may not support CC 99 `set` with userIdStatus=0 for clearing — these would fail with a Z-Wave error, preventing deletion. Mitigation: the user can fall back to clearing the slot via Z-Wave JS UI directly.
- FLiRS (sleeping) locks may respond slowly to the clear command, potentially causing timeouts. The default 10s timeout should be sufficient for single-slot operations.
