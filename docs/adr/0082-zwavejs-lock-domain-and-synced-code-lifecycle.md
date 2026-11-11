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

**Synced codes' locks are editable.** `lock_entity_ids` is no longer read-only, and neither are `add_lock_entity_ids` and `remove_lock_entity_ids` (issue #159). A synced code's locks are added and removed the same way a manual code's are: latchpoint pushes the code's PIN into a free slot on an added lock through the queued push (ADR-0111) and tracks that slot on the code's assignment, and clears the slot on a removed lock through the normal clear and pending removal path, including the lock the code was imported from. The code stays `source=synced` while the lock it was imported from is still on it (issue #222, below). The PIN, the schedule (`days_of_week`, `window_start`, `window_end`) and `max_uses` still come from the lock and stay read-only, and `is_active`, `start_at` and `end_at` only open up under ADR-0109's rule for synced codes with an `end_at`. The real case is a master code imported from the Front Door that also has to open the Back Door.

- A synced code imported from a lock that masks its codes has no stored PIN, so adding a lock to it is a 400 ("Latchpoint doesn't have a readable PIN for this code, so it can't put it on another lock."), and so is one whose stored PIN can't be decrypted. Removing one still works, since a clear doesn't need the PIN.
- Adding a lock is refused with a 409 when another code already has the PIN on that lock, the same check turning a code on uses (issue #188), against the added locks only. That goes for active manual codes too.
- Removals that would leave a synced code with no locks are a 400, a full `lock_entity_ids: []` included, since the door codes list leaves out a synced code with no locks.
- Lock sync treats the pushed slot as the code's own, since the code tracks it: it isn't imported as a "Slot N" code and the code isn't flagged `duplicate_pin` against itself. A slot latchpoint pushed (its assignment holds a slot and has a push attempt, which lock sync never stamps) gets the manual code rule from issue #166. When it's occupied, lock sync only marks that lock pushed and flags a disabled slot, skips it as `pin_mismatch` when it holds another PIN, and never takes the code's PIN, active flag, schedule or owner from it, whether the code is on or off. When the value cache calls it Available it's only let go after a live readback answers empty twice, then pushed again, and the code is never turned off for it. The slot on the lock the code was imported from keeps the synced rule above, so that lock alone decides the code's PIN, schedule, owner and active flag. A code it turns off comes off the added locks once two live reads confirm it (issue #221, below).
- A new PIN or schedule lock sync takes from the lock the code was imported from goes on to the added locks (issue #220). The sync holds only that lock's `lock_sync:` lock, so it sends nothing to them. It sets `reconcile_requested_at` on each added lock (re-arming one the cap or a held PIN failed) and wakes the queued push task once it commits. The code shows pending with "Waiting to send the code's new PIN or schedule to this lock." for each of them.
- Every push records what it wrote into the slot on the assignment: `written_pin` (encrypted like the code's PIN) and `written_schedule` (a fingerprint of the days and window, `""` for none). Migration 0012 adds those two columns and `reconcile_requested_at`, all nullable, no backfill. Null means not known.
- One step, `added_lock_reconcile.reconcile_added_lock`, owns every change to a flagged added lock. The queued push task runs it for a lock flagged within the last 10 minutes and not tried since, and `push_pending_door_codes` retries the rest every 300s under the attempt cap. It runs under that lock's `lock_sync:` lock and each time reads the code's current PIN and schedule and the slot live, then:
  - the slot holds the code's PIN: it's kept. If the schedule written there isn't the code's, the new one is sent into the slot when it keeps every day the written one had (a first schedule included), and otherwise the slot is cleared and pushed again, since the schedule push never takes a day away. A schedule nothing is recorded for is cleared and pushed again too. A schedule push sets `written_schedule` to unknown before it sends anything and records the schedule only once all of it went out, so one that stops partway leaves unknown, not the old value
  - the slot holds the PIN latchpoint last wrote there, or a code the lock won't show: it's latchpoint's older PIN, so it's cleared and the code pushed again
  - the slot holds any other PIN (typed in at the keypad, the `pin_mismatch` case), or nothing: latchpoint lets go of it without touching it and pushes the code into a free slot. That's only for a slot whose `written_pin` a push recorded. A slot latchpoint pushed before 0012 has nothing recorded and may have fallen behind more than one change, so any readable PIN in it but the code's is taken as latchpoint's and cleared, like every clear did before (lock config, messaging or passage mode, is still let go). That takes a second read of the slot's status, and only a reported user code, enabled or disabled, counts; any other answer is no verdict, so nothing is cleared and the run is tried again. A delete clears it the same way
  - no slot: the code is pushed, which adopts an unconfirmed attempt holding its current PIN. Before that, slots an unconfirmed push left an older PIN in are read back and cleared when they still hold it
- The flag is only cleared when it's still the one the run read, and a run that found it set again goes again right away, so a sync that changes the code while a push is running gets the newest PIN or schedule out. Nothing needs re-checking at commit, because the push records what it really wrote and the next run compares that with the code.
- A code that's outside its dates or being dropped from the lock keeps the flag and its old PIN and window on the added locks (ADR-0109) until it's back on. So does one that's off, unless its import lock confirmed the off live (issue #221, below), in which case the reconcile takes the PIN off instead. When the import lock's sync turns it back on, the added locks still flagged, or recorded as holding another PIN or schedule than its own (or no longer a slot), are flagged again from then, so the queued push task takes them up at once however long it was off. One with nothing recorded and no flag waits for the next real change instead of being cleared for an off and on. Turning a dated synced code on from latchpoint (anything that queues its push) and the code reaching its `start_at` take up an old flag the same way. A reconcile that fails counts on the lock's attempts and fails it at the cap, except one that ran out of its time budget, like a push. It never records a clear failure, so it can't hold back the import lock's sync, which still decides the PIN and turns the code off. Retry flags the lock again and runs it.
- While a lock is flagged, nothing else pushes it: a push, the schedule-only one included, checks the flag once it holds the lock and sends nothing on a flagged lock unless the reconcile called it, so one that picked the lock before lock sync flagged it can't write over the reconcile. The clear retries aren't gated: they only clear a slot that reads back with the PIN they were recorded for, or the slot the code tracks, which never writes a PIN or schedule, and holding one back would leave a clear failure holding back the import lock's sync. Also while it's flagged, the Back Door's own sync skips the slot as `update_pending`, the scheduler's state repair and the #180 attempt check leave it alone, and a delete reads the slot and only clears it when it holds the code's PIN, the PIN latchpoint wrote there, a code the lock won't show, or any PIN in a slot with nothing recorded.
- A new PIN is only taken from the lock the code was imported from, and so only sent on, when a live CC 99 `get` of the slot reports it. A new schedule, one removed included, is only taken when a live CC 78 read of the slot's daily repeating entries gives it, unless the sync's schedule read was live already (a lock with no CC 78 values in the cache). A value only the cache has (stale, or cached for a `set` the lock dropped) would take a working PIN or window off the added locks. Until a sync's readback confirms it, or when the read doesn't fit the sync's readback budget, the code keeps its PIN or schedule and the slot gets `pin_change_unconfirmed` or `schedule_change_unconfirmed`. A lock that masks its codes gives no PIN, so nothing changes and nothing is sent. Codes on that lock alone take a new PIN and schedule as before, without a readback.
- An added lock where another code already has the new PIN (in a slot, or active and waiting for its push, issue #188) still gets the old PIN cleared, since it was changed on purpose, but the code isn't pushed there. The lock is failed with "… already has this PIN in slot N as door code M, so this code is off that lock. Delete that code, then Retry.", and the sync's slot gets `pin_held_on_other_lock`. A later change at the import lock to a PIN that doesn't clash flags it again and brings it back.
- A synced code the lock it was imported from turns off comes off the added locks (issue #221), but only once the import lock confirms it live, so a stale value cache never takes a PIN that works off another door. When the sync's cache read calls the code's slot there Available, or Occupied/Disabled, and the code is on other locks too (on, or off with a slot or an unconfirmed push still on one of them, a lock being dropped aside), the slot is read back first, inside the sync's readback budget and before it writes anything: a live CC 99 `get` has to answer Available twice (the same readback #214 uses for a manual code), or report a disabled user code on two `get`s in a row. Anything else, an enabled code, one empty answer then the PIN or no answer, an error or no budget left, isn't confirmation: an empty slot is skipped as `slot_not_confirmed_empty` with the code left on and the slot kept, and a disabled one leaves the code on with `off_change_unconfirmed`. A code only on its import lock still goes by the cache read like before. Disabled counts as off here, as it always has for a synced code (ADR-0109), since a disabled slot doesn't open the import lock either; #214's rule that a disabled slot leaves a code on is for latchpoint's own slots (manual codes and pushed ones), not the import lock's.
- Once confirmed, the sync turns the code off (or keeps it off), lets go of an empty slot like before, and flags the added locks that may hold the PIN (a slot the code tracks there, or an unconfirmed push) with "Waiting to take the PIN off this lock, since the code is off at the lock it was synced from." Ones with nothing on them yet (a push still queued, or a lock failed for #188) are left alone. A push whose `set` is already out when the code goes off (the sync only holds the import lock) is caught by the push itself: once the slot is recorded, or the attempt is if it isn't confirmed, it looks at the code again under its row lock while it still holds the lock, and when it's a synced code that's off now it flags the lock as of the newest `off_confirmed` event and runs the take-off right there. That can only be the sync's confirmed off, since every other way an active code goes off holds that lock too. Its schedule isn't sent then. The slot's `code_synced` event gets `off_confirmed` and `taken_off_lock_entity_ids` right after the flags, and the slot result gets `taking_off_other_locks` when the slot is still there. Nothing is sent from the sync, which only holds the import lock.
- That event is what lets the reconcile clear an off code's lock (`added_lock_reconcile.off_clear_q`): the lock is flagged, the code is a synced code that's off, and it has an `off_confirmed` event no older than the flag. So a flag set any other way stays waiting while the code is off: a new PIN taken while it was off, a #223 flag from before this, or a code a cache read turned off before this change. A sync of the import lock that confirms such a code off (its slot is still tracked there and reads disabled or empty) flags its added locks the same way, which is how codes from before this get taken off. Retention keeps an `off_confirmed` event while a flag it's for is still set.
- The queued push task and the 300s retry run those locks like any other reconcile, under the lock's `lock_sync:` lock. Instead of pushing, it reads back and clears slots an unconfirmed push may have left any PIN of the code in (the current one too, since nothing will adopt it), then reads the tracked slot with the delete's rule: it's cleared when it holds the code's PIN, the PIN latchpoint wrote there or a code the lock won't show, and let go untouched when it holds someone else's PIN or nothing. Unlike the delete and the reconcile of a new PIN, a slot with nothing recorded (before 0012) holding another readable PIN is let go too, since the take-off knows the code's PIN is what should be there and the other one may be a keypad code. `written_pin` and `written_schedule` are kept with no slot, so when the import lock turns the code back on the lock reads as behind it and is flagged again, and the reconcile pushes it into a free slot within seconds. A lock from before 0012 has nothing recorded, so it isn't flagged then, and the scheduler's 300s push puts it back. Failures count on the lock's attempts and fail it at the cap, never as clear failures, so the import lock's sync isn't held back by them and can still turn the code back on. While any of them are left (a lock being dropped aside, which is its clear's), the code is `pending` (`failed` once one is), with the lock's message in its error, and each one's `lock_slot_assignments` entry has `taking_pin_off`. The card shows that lock as clearing (clear failed at the cap) and the badge as Pending clear (Clear failed) with Retry, like a `pending_slot_clears` entry. Retry on the code runs them again in the request without touching their flag, which would lose the confirmation.
- It's the reconcile rather than the #167 inactive clear because the reconcile already owns every write to a synced code's added lock, reads the slot with #223's rule, and never records a clear failure. The #167 clear reads the slot with the older manual rule, doesn't know `written_pin`, and records clear failures, which would make the import lock's sync skip the code's slot as `clear_outstanding` while the added lock is offline, so it couldn't be turned back on there until that lock answered.
- Manual codes keep their own paths: an edit clears and pushes their locks itself, under all their `lock_sync:` locks.
- Adding a lock to a synced code is checked for another code with the PIN on that lock whether the code is on or off, since lock sync turns an undated one back on without that check.
- ADR-0109's stranded copy rule never retires a synced code latchpoint has pushed to a lock. It's only flagged.
- A lock change that leaves a synced code with no import lock makes it a manual code (issue #222). An import lock is one latchpoint never tried or queued a push to (no `last_push_attempt_at` or `push_requested_at`, which lock sync never stamps), slot or not, that the code isn't being dropped from and that wasn't added in the same save. A lock added in latchpoint gets `push_requested_at` when it's added, even to a code that's off or not started and so isn't pushed yet, so it's never taken for an import lock. With the import lock removed (its clear still pending included), or removed and added back (which makes it a pushed lock), lock sync treats every slot the code has like a manual code's, so nothing would change its PIN, active flag or schedule again and the edit form would keep them read-only. The save sets `source=manual` under every lock the code is on, makes a permanent code with dates temporary so its dates stay editable, and records it on the `code_updated` event (`source` in `updated_fields`, and `source_changed` with `reason=no_import_lock`). An added lock still flagged for its reconcile, or recorded as holding another PIN or schedule than the code's, may still have the older one. Unconfirmed attempt slots are read back and cleared when they hold the PIN, and the tracked slot is read back with the reconcile's and the delete's rule: it's cleared when it holds the code's PIN, the PIN latchpoint wrote there or a code the lock won't show (or any user code when nothing is recorded), and let go untouched when it holds someone else's PIN or nothing. Either way the code is pushed into a free slot. A clear that fails keeps the slot for the scheduler's retries, and a read with no answer lets the slot go and records an unconfirmed clear expecting the PIN latchpoint wrote there, so the retry reads it back before it clears anything. When nothing is recorded there (a lock pushed before 0012), a read with no answer keeps the slot tracked with a plain clear failure instead, so the retry clears it like a delete would. A lock where another code already has the code's PIN (#188) isn't pushed: once its slot is off it, it's failed with "… already has this PIN in slot N as door code M, so this code is off that lock. Delete that code, then Retry.", like the reconcile does. Every reconcile flag on the code is dropped, so the reconcile never writes to it after. From then on it's a manual code: lock sync keeps it manual and never takes its PIN, active flag, schedule or owner (#166, #214), it's never a stranded copy (#211), an off one comes off its locks through the #167 inactive clear, and delete, Retry and the clear retries take the manual paths.
- Only a save that adds or drops a lock does that, so a full `lock_entity_ids` naming the locks the code already has doesn't. A synced code an older sync converted from a pushed manual code, or a dated one latchpoint pushed again after its retire (#189), has no import lock either, but stays synced until its locks are edited. A row whose slot lock sync let go of when it read empty still counts as an import lock (lock sync made it), so a code turned off that way stays synced until that row is removed too. So does a lock added to an off code before the `push_requested_at` stamp above, which has nothing on its row to tell it apart.

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

Some synced codes are deleted the way a manual code is instead: clears an earlier save couldn't finish are retried, a clear that fails is recorded for the scheduler's retries, unconfirmed push slots are read back and cleared, and when any of that can't be done the delete is refused with "The door code wasn't deleted and is now off", with the slots it did clear forgotten. That's a synced code latchpoint has ever pushed or queued a push of to any lock (an assignment with `last_push_attempt_at` or `push_requested_at`, which includes rows migration 0010 stamped from the code's last attempt and a dated synced code turned back on under ADR-0109), or one that still has a clear failure or an unconfirmed push attempt on record, on a lock it's on or one it was removed from (§2). Fail-fast there would leave the row saying a slot it already cleared is still held, with nothing recorded to retry, or delete the row along with the record of a slot only latchpoint knew about and leave the PIN in it. Every other synced code keeps the fail-fast. The clears a refused delete left are on record, so the scheduler's clear retries take them up on their own every 300s (under the code's clear-retry cap), and Retry runs them too. A slot on an added lock whose read before the clear got no answer is let go and recorded as an unconfirmed clear expecting the PIN latchpoint wrote there, the same as #222's conversion does, so the retry reads it back and leaves a PIN someone typed in since alone instead of clearing the slot blind (issue #221). One with nothing recorded (pushed before 0012) stays tracked with a plain clear failure, like before. Retry on a refused synced code that's off only answers 409 once nothing is left to clear, and then says so and to delete it again to finish, since an undated one can't be turned on from latchpoint.

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
