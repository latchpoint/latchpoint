# ADR 0082: Z-Wave JS Lock Domain Assignment, Synced Code Read-Only Enforcement, and Physical Code Deletion

## Status
**Proposed**

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

### 2. Enforce read-only editing for synced door codes (label-only)

`DoorCodeUpdateSerializer` rejects updates to all fields except `label` when the code's source is `SYNCED`. The rejected fields are:

- `code` (PIN)
- `is_active`
- `start_at`, `end_at`
- `days_of_week`
- `window_start`, `window_end`
- `max_uses`
- `lock_entity_ids`

This validation is applied at the serializer level, so the use-case layer doesn't need to know about source-based restrictions. The user can still rename a synced code's label for organizational purposes.

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
  │   │   ├─ Mark assignments sync_dismissed=True
  │   │   ├─ Set code.is_active=False
  │   │   └─ Create DoorCodeEvent(CODE_DELETED, metadata={cleared_from_lock: true})
  │   │
  │   └─ Any clear failed:
  │       └─ Raise error, no DB changes (Option A: fail-fast)
  │
  └─ code.source == MANUAL?
      └─ Hard-delete code (existing behavior, unchanged)
```

#### Error handling: Option A (fail the delete)

If the Z-Wave JS server is unreachable or the lock doesn't respond, the `invoke_cc_api` call raises a `ZwavejsCommandError` (subclass of `GatewayError`), which the exception handler maps to HTTP 502. The database state is unchanged — the user must retry when the lock is reachable.

**Rationale for Option A over alternatives:**

- **Option B** (dismiss + queue retry) adds background job complexity and risks "phantom" codes that appear deleted in the UI but persist on the lock indefinitely if retries exhaust.
- **Option C** (dismiss + warn) provides poor UX — the user thinks the code is deleted but must remember to manually clear the lock.
- **Option A** is simple, transparent, and ensures DB and lock stay in sync. The failure case (lock offline) is visible and actionable.

#### Idempotency

Clearing an already-empty slot via `clear(slot_index)` is safe — the lock accepts the command without error. This means retrying a failed-then-recovered delete operation is harmless even if some slots were cleared before the failure.

#### Gateway helper

A `clear_lock_user_code_slot()` function is added to `locks/use_cases/lock_config_sync.py`, co-located with `_resolve_lock_node_id()` and the existing CC 99 sync logic. It resolves the lock entity ID to a Z-Wave node ID and invokes `CC 99 clear(slot_index)`.

## Consequences

### Positive
- Lock entities are discoverable by `domain="lock"` for UI rendering and lock-centric features
- Synced codes cannot silently diverge from physical lock state through edits
- Deleting a synced code is a real operation — the physical lock slot is cleared, not just hidden
- `clear_lock_user_code_slot()` is reusable for future features (e.g., bulk slot management, code rotation)
- Existing dismiss/undismiss mechanism is preserved as a fallback audit trail

### Negative
- Deleting a synced code now requires the lock to be online and reachable via Z-Wave JS
- CC API calls generate RF traffic to the lock during deletion (one call per lock assignment)
- Entity sync slightly increases logic complexity with the lock representative selection

### Risks
- Some lock firmwares may not support CC 99 `set` with userIdStatus=0 for clearing — these would fail with a Z-Wave error, preventing deletion. Mitigation: the user can fall back to clearing the slot via Z-Wave JS UI directly.
- FLiRS (sleeping) locks may respond slowly to the clear command, potentially causing timeouts. The default 10s timeout should be sufficient for single-slot operations.
