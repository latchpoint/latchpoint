# ADR 0068: Z-Wave JS Lock Config Sync (Codes & Schedules)

## Status
**Implemented**

## Context
Door codes and schedules are currently created and managed entirely within LatchPoint. There is no mechanism to import existing user codes or schedule slots that are already programmed on a physical Z-Wave lock.

This is a problem for users who:
- Already have user codes set on their locks before adopting LatchPoint.
- Program codes through another controller (e.g. the Z-Wave JS UI) and want LatchPoint to stay in sync.
- Want to verify that LatchPoint's view of lock state matches the hardware.

### Data source: Z-Wave JS cache, not the physical lock

LatchPoint does **not** communicate with lock hardware directly. The existing `node_get_value()` method reads from Z-Wave JS's **in-memory driver cache** (no RF traffic to the lock). The Z-Wave JS driver populates this cache by interviewing each node on startup and by processing unsolicited value reports.

This means:
- **Codes set via the Z-Wave JS UI** (or any Z-Wave JS client) are already in the cache and can be read immediately — no lock communication needed.
- **Codes set directly on the lock keypad** will only appear in the cache after Z-Wave JS re-interviews the node (the lock sends an unsolicited User Code report for keypad-programmed codes on most firmwares, but this is not guaranteed).
- **Freshness is Z-Wave JS's responsibility.** If a user suspects the cache is stale, they can trigger a node re-interview from the Z-Wave JS UI. LatchPoint does not need to implement its own RF polling.

The Z-Wave JS connection manager (`integrations_zwavejs/manager.py`) already supports reading and writing arbitrary node values via `node_get_value()` and `set_value()`. Z-Wave locks expose user codes through **Command Class 0x63 (User Code)** and schedule data through **Command Class 0x4C (Schedule Entry Lock)**, both accessible as standard Z-Wave JS value IDs.

The existing `DoorCode` model already has fields for schedules (`start_at`, `end_at`, `days_of_week`, `window_start`, `window_end`) and lock assignments (`DoorCodeLockAssignment`), but these are only populated by manual user input today.

### Prior sync infrastructure — removed in migration 0002

An earlier iteration of the codebase included sync-related fields that were deliberately stripped out in `locks/migrations/0002_remove_door_lock_and_sync_fields.py`:

- `DoorCodeLockAssignment` originally had `code_slot` (PositiveIntegerField), `sync_status` (pending/synced/failed), `last_synced_at`, and `sync_error`.
- A `DoorLock` model existed with `entity_id`, `name`, `supports_code_slots`, `max_code_slots`, `is_available`, `last_seen_at`, `manufacturer`, and `model`.

These were removed because the original design assumed LatchPoint would maintain its own lock inventory and per-assignment sync state machine. This added complexity without a working sync implementation to justify it.

This ADR takes a simpler approach:
- **No `DoorLock` model.** Lock identity comes from the entity registry (already maintained by `entity_sync.py`). A dedicated lock model duplicates data without adding value.
- **`source` field on `DoorCode`, not per-assignment `sync_status`.** The question "where did this code come from?" is a property of the code itself, not of each lock assignment. A `source` field is simpler than a three-state sync state machine and sufficient for pull-only sync.
- **`slot_index` on `DoorCodeLockAssignment`, not `code_slot`.** Same concept, different name. The new field is nullable (manual codes have no slot) and carries a unique constraint with `lock_entity_id` to enforce slot-level idempotency.

### Relevant ADRs
- **ADR 0012** — Z-Wave JS Gateway + Connection Manager (transport layer)
- **ADR 0056** — Door Codes UI Simplification (current UX)
- **ADR 0003** — Separate Entity Import from Alarm Configuration (entity registry pattern)
- **ADR 0057** — Integration Entity Updates Trigger Rules (dispatcher events)
- **ADR 0069** — Lock Config Sync: Operational, Security & UX Concerns (companion)

## Decision
Add a **lock config sync** capability that reads user codes and schedule slots from a Z-Wave JS lock and imports them into LatchPoint's `DoorCode` model.

### Scope
1. **Read user-code slots** — Query CC 0x63 to enumerate all programmed user-code slots on a lock node. For each occupied slot, record the slot index, code status (enabled/disabled), and PIN (if the lock firmware exposes it).
2. **Import into DoorCode** — Create or update `DoorCode` records from the synced data, linking them to the lock via `DoorCodeLockAssignment`. Mark imported codes with a new `source` field so they can be distinguished from manually created ones.
3. **Conflict resolution** — When a sync finds a slot that already maps to an existing `DoorCode`, prefer Z-Wave JS's cached state (Z-Wave JS is the source of truth for LatchPoint) but flag the conflict in the sync result so the user can review.
4. **Dismissed-slot tracking** — When a user deletes a previously-synced code in LatchPoint, record the dismissed `(lock_entity_id, slot_index)` so re-sync does not recreate it. Dismissed slots appear in the `SyncResult` for transparency but are not re-imported unless the user explicitly re-enables them.
5. **Audit trail** — Record `DoorCodeEvent` entries with event type `code_synced` for every imported or updated code.

### Design Details

#### New backend module: `locks/use_cases/lock_config_sync.py`
- `sync_lock_codes(lock_entity_id: str) -> SyncResult` — orchestrates the full read-and-import cycle for a single lock.
- Uses the `ZwavejsGateway` protocol (not the manager directly) for testability.
- Returns a `SyncResult` dataclass summarising slots read, codes created, codes updated, conflicts, and errors.

#### New API endpoint
- `POST /api/locks/{lock_entity_id}/sync-config/` — triggers a sync for the specified lock. Requires admin role. Returns the `SyncResult` in the standard ADR 0025 response envelope.

**Request body:**
```json
{
  "reauth_password": "string",
  "user_id": "uuid (owner for imported codes)"
}
```

**Validation and error responses:**

| Scenario | HTTP Status | Detail |
|---|---|---|
| `lock_entity_id` not found in entity registry | 404 | `"Lock entity not found."` |
| Entity exists but is not linked to a Z-Wave JS node | 400 | `"Lock entity is not linked to a Z-Wave JS node. Sync Home Assistant entities first."` |
| Entity exists but node does not expose CC 0x63/99 (User Code) value IDs | 400 | `"Lock does not expose User Code (CC 99) value IDs."` |
| Z-Wave JS not connected | 503 | `"Z-Wave JS is not reachable."` (exact message depends on gateway error) |
| Sync already in-flight for this lock | 409 | `"A sync is already in progress for this lock."` |
| Admin reauth fails | 403 | `"Re-authentication failed."` |
| `user_id` not found | 404 | `"User not found."` |

**Entity resolution:** The endpoint expects a lock entity id from the entity registry (typically a Home Assistant `lock.*` entity). It looks up the `Entity` record, extracts `node_id` from `Entity.attributes["zwavejs"]["node_id"]`, then verifies the node supports CC 0x63 (User Code) by checking `node_get_defined_value_ids()` for `commandClass: 99`. The `lock_entity_id` stored on synced `DoorCodeLockAssignment` records is the same `lock_entity_id` passed to the endpoint.

**Success response (200):**
```json
{
  "data": {
    "lock_entity_id": "lock.front_door",
    "node_id": 5,
    "created": 2,
    "updated": 1,
    "unchanged": 0,
    "skipped": 0,
    "dismissed": 0,
    "deactivated": 0,
    "errors": 0,
    "timestamp": "2026-02-08T00:00:00Z",
    "slots": [
      {
        "slot_index": 1,
        "action": "created",
        "door_code_id": 123,
        "pin_known": true,
        "schedule_applied": false,
        "schedule_unsupported": false,
        "error": null
      }
    ]
  }
}
```

#### DoorCode model changes
- Add `source` field (`CharField`, choices: `manual`, `synced`, default `manual`) to distinguish user-created codes from hardware-synced ones. The `synced` value means "imported from lock hardware via Z-Wave JS." If future integrations introduce other sync sources (e.g. cloud services), new choices can be appended without migrating existing rows.

#### DoorCodeLockAssignment model changes
- Add `slot_index` field (`PositiveSmallIntegerField`, nullable) to track which physical slot on the lock a code occupies. This field lives on the assignment (not `DoorCode`) because a code can be assigned to multiple locks and may occupy different physical slots on each.
- Add `sync_dismissed` field (`BooleanField`, default `False`). Set to `True` when a user deletes a previously-synced code in LatchPoint. On re-sync, assignments with `sync_dismissed=True` for a given `(lock_entity_id, slot_index)` are skipped. The user can clear the dismissal via the UI to re-enable sync for that slot.
- Add unique constraint on `(lock_entity_id, slot_index)` to prevent duplicate slot mappings. The constraint uses `condition=Q(slot_index__isnull=False)` so manual codes (no slot) are excluded.

#### Frontend
- Add a "Sync Codes from Lock" admin-only section on the Door Codes page (visible when at least one Z-Wave-linked lock entity exists).
- Show sync results in a summary dialog (created, updated, unchanged, deactivated, errors).
- Synced codes display a badge or icon indicating their source.

### What this ADR does NOT cover
- **Push sync** (writing LatchPoint codes to the lock hardware). This is a separate, higher-risk operation and should be its own ADR.
- **Automatic/scheduled sync**. Initial implementation is manual-trigger only.
- **Non-Z-Wave locks**. Only Z-Wave JS locks are in scope.
- **Full CC 0x4C (Schedule Entry Lock) schedule sync.** For v1, LatchPoint only imports simple weekday schedules that map exactly to the `DoorCode` model (single window, same start/end across selected weekdays, and no midnight crossing). Year-day schedules, daily repeating schedules, multiple windows per day, or different windows per weekday are treated as unsupported and are not imported (codes are still imported). A future ADR can address full-fidelity schedule support alongside a schedule model redesign.

## Alternatives Considered

### 1. Bidirectional sync in one ADR
Combining read (pull) and write (push) sync in a single feature. Rejected because push-sync has different failure modes (lock may reject codes, slot capacity limits) and different security implications (accidentally overwriting lock codes). Better to ship pull-sync first, validate the model, then layer push-sync on top.

### 2. Treat Z-Wave JS as authoritative and discard local codes
On every sync, delete all LatchPoint codes for the lock and re-import from Z-Wave JS. Simpler but destructive — loses any LatchPoint metadata (labels, code types, audit history) that Z-Wave JS doesn't store.

### 3. Only sync slot metadata, not PINs
Some lock firmwares do not return the actual PIN for occupied slots (only status). We could sync only slot status and require the user to re-enter PINs. This is the fallback behavior for locks that mask PINs, but for locks that do expose PINs we should import them.

## Consequences
- `DoorCode` gains one new field (`source`) and `DoorCodeLockAssignment` gains two (`slot_index`, `sync_dismissed`), requiring a migration.
- Sync reads from the Z-Wave JS driver cache (in-process, no RF traffic). Multiple value reads go through the WebSocket to the Z-Wave JS server but are cache lookups. For each occupied slot, the sync reads `userIdStatus` and `userCode` — **2 WebSocket round-trips per slot**. A lock with 30 occupied slots requires ~60 WebSocket calls. Using `node_get_defined_value_ids()` first (one call) to discover occupied slots reduces unnecessary reads for empty slots.
- **PIN hashing is CPU-intensive.** Each imported PIN is hashed via `make_password()` (Django's PBKDF2 by default). For 30 occupied slots, this is ~30 PBKDF2 hash operations, which may take 5–10 seconds of CPU time depending on iteration count. Combined with WebSocket round-trips, a full sync could take 15–40 seconds. The endpoint must set an appropriate request timeout and the frontend should show a loading indicator.
- LatchPoint depends on Z-Wave JS cache freshness. If the cache is stale (e.g. codes changed on the keypad and the lock didn't send an unsolicited report), the sync will import stale data. This is acceptable because cache freshness is Z-Wave JS's domain, and users can re-interview the node from the Z-Wave JS UI.
- Imported codes that lack a PIN (lock firmware masks them) will be stored with `code_hash=None` and flagged as "PIN unknown" in the UI — the user must re-enter the PIN to use schedule or validation features.
- The `DoorCodeLockAssignment` unique constraint on `(lock_entity_id, slot_index)` prevents accidental duplicates but means re-syncing the same lock is idempotent.
- **Dismissed slots survive re-sync.** When a user deletes a previously-synced code, the assignment is soft-marked as `sync_dismissed=True` (rather than CASCADE-deleted). Re-sync skips dismissed slots, preventing zombie code re-creation. This trades a small amount of schema complexity for data integrity in the matching logic.

## Review Findings

Deep review against the existing codebase surfaced the following issues. This section focuses on the **core sync data flow** (read → parse → match → create/update). Peripheral concerns (security, concurrency, operational, UI/UX) are tracked in **ADR 0069**.

### What the ADR gets right

- **Pull-only scope** — shipping read before write is the correct risk-reduction strategy.
- **Z-Wave JS cache, not RF** — correctly identifying that `node_get_value()` reads from cache.
- **Manual trigger only** — deferring automatic sync is appropriate for v1.
- **Audit trail** — using the existing `DoorCodeEvent` model with `code_synced` events (`CODE_SYNCED` already defined at `locks/models.py:111`).
- **Gateway Protocol for testability** — using `ZwavejsGateway` protocol, not the manager directly.
- **Existing infrastructure** — the codebase already has all the building blocks (gateway methods, use case patterns, `entity_sync.py` as a reference implementation).

### Model incompatibilities — must fix before implementation

**1. `slot_index` is on the wrong model.**
The ADR adds `slot_index` to `DoorCode` but then places a unique constraint on `(lock_entity_id, slot_index)` in `DoorCodeLockAssignment`. This is contradictory — `lock_entity_id` lives on `DoorCodeLockAssignment`, not `DoorCode`. More fundamentally, a door code can be assigned to multiple locks and could occupy different physical slots on each. `slot_index` is a per-lock-assignment property and must live on `DoorCodeLockAssignment`.

**2. `code_hash` is not nullable — storing `None` will fail.**
The Consequences section assumes `code_hash=None` for masked PINs, but the model defines `code_hash = models.TextField()` with no `null=True` or `blank=True` (`locks/models.py:20`). The migration must make `code_hash` nullable (or use a sentinel like empty string) for synced codes with unknown PINs.

**3. `pin_length` has a CHECK constraint requiring 4–8 — incompatible with masked PINs.**
`locks/models.py:23-25` enforces `MinValueValidator(4)` / `MaxValueValidator(8)`, and a DB-level CHECK constraint repeats this (`models.py:57-60`). If the PIN is masked, its length is unknown. Options: make `pin_length` nullable and add a condition to the constraint (e.g. only enforce when `source='manual'`), or store 0 and relax the constraint.

**4. `DoorCode.user` is a required FK — synced codes have no owner.**
`DoorCode.user` is `ForeignKey(User, on_delete=CASCADE)` with no `null=True` (`locks/models.py:19`). Z-Wave JS has no concept of user ownership. The ADR must specify who owns synced codes: the admin who triggered the sync, a user selected in the UI (via the existing owner selector), or a dedicated system user. This also affects the API contract — does the POST endpoint accept a `user_id` parameter?

### Core sync flow gaps — reading from Z-Wave JS

**5. No Z-Wave value_id specifications for CC 0x63 queries.**
The ADR says "query CC 0x63" but never specifies the actual `value_id` dicts the use case must construct for `node_get_value()`. The required value_ids are:
- `{commandClass: 99, property: "usersNumber"}` — reports the lock's max slot count.
- `{commandClass: 99, property: "userIdStatus", propertyKey: <slot>}` — per-slot status (Occupied/Enabled, Occupied/Disabled, Available, etc.).
- `{commandClass: 99, property: "userCode", propertyKey: <slot>}` — per-slot PIN (if firmware exposes it).
Without these, the implementation must reverse-engineer the Z-Wave JS value ID structure from scratch.

**6. CC 0x4C (Schedule Entry Lock) is only partially supported.**
CC 0x4C exposes multiple property types — `weekDaySchedule`, `yearDaySchedule`, `dailyRepeatingSchedule` — each with different multi-entry, per-user-code `propertyKey` structures. The `DoorCode` model can only represent a single weekday window. For v1, import only weekday schedules that map exactly to that model, and treat all other schedule forms as unsupported (skip schedule import but still import the code slot).

**7. Slot enumeration strategy is unspecified.**
The ADR says "enumerate all programmed user-code slots" but never specifies *how*. The recommended approach:
1. Read `usersNumber` to learn the max slot count.
2. Read each slot's `userIdStatus` to identify occupied slots.
3. Only read `userCode` (the PIN) for occupied slots — skip empty and disabled-without-PIN slots.
Alternative: call `node_get_defined_value_ids(node_id)` once, filter for `commandClass: 99` value IDs in-process, then read only matched values. This is the pattern `entity_sync.py` already uses and significantly reduces WebSocket traffic.

**8. WebSocket round-trip count is underestimated.**
The original Consequences section said "locks with many slots (e.g. 30+) may still take a few seconds." For each occupied slot: (a) `userIdStatus`, (b) `userCode` — that's **2 round-trips per slot**. For 30 slots, ~60 WebSocket calls. Combined with `make_password()` CPU cost (~0.2–0.3s per hash), total sync time for 30 slots is 15–40 seconds. The use case should batch-read via `node_get_defined_value_ids()` first (one call), filter in-process, then read only occupied-slot value IDs to minimize traffic.

**9. Return type of `node_get_value()` for user codes is unspecified.**
`node_get_value()` returns `getattr(value_obj, "value", None)` — a raw Python value. For `userCode`, this could be a string (`"1234"`), a bytes buffer, or an integer. The sync code must coerce this to a string before passing to `make_password()`. The ADR should document the expected return type or specify a normalization step.

**10. No handling of slot 0 (master code).**
In Z-Wave, user code slot 0 is typically the master/programming code. It should **not** be imported as a regular door code — it has a different security role and is not a "user" code. The sync must skip slot 0 (or make this configurable).

### Core sync flow gaps — matching and importing

**11. No mapping from `lock_entity_id` to Z-Wave JS `node_id`.**
The endpoint accepts `lock_entity_id`, but querying CC 0x63 requires a Z-Wave JS `node_id`. The entity registry stores `node_id` in `Entity.attributes["zwavejs"]["node_id"]` (populated by `integrations_zwavejs/entity_sync.py:133-138`). Resolution strategy: accept any Z-Wave JS entity ID belonging to the lock node, look up the `Entity` record, and extract `node_id` from attributes.

**12. Which `lock_entity_id` to store on synced `DoorCodeLockAssignment`s.**
A Z-Wave lock node generates many entity IDs (one per value_id): `zwavejs:...:98:currentMode:0` (Door Lock CC), `zwavejs:...:99:userCode:1` (User Code CC), etc. The `lock_entity_id` stored on synced assignments should be the **Door Lock CC entity** (CC 0x62/98, `currentMode` property) — the entity that represents the lock *as a lock*, consistent with what HA-originated assignments would use. The use case should resolve this canonical entity from the node's value_id list.

**13. Matching logic for "slot already maps to existing DoorCode" is undefined.**
The ADR says "when a sync finds a slot that already maps to an existing `DoorCode`, prefer Z-Wave JS's cached state." But *how* is the match found? Presumably by `(lock_entity_id, slot_index)` on `DoorCodeLockAssignment`. This works for previously-synced codes. But if a user manually created a code (no `slot_index`) and the same PIN occupies a slot on the lock, sync creates a **duplicate** `DoorCode` for the same physical code — there is no PIN-based deduplication because manual codes store only a hash. The ADR should explicitly state: matching is by `(lock_entity_id, slot_index)` only; manual codes are never matched to slots; the user must manually reconcile duplicates.

**14. What happens when a previously-synced slot becomes empty on re-sync.**
First sync: slot 5 is `Occupied/Enabled` → `DoorCode` created with `source=synced`. User deletes the code from the lock keypad. Re-sync: slot 5 is now `Available`. Options:
- **Deactivate**: set `is_active=False` on the existing `DoorCode` and flag in `SyncResult`.
- **Delete**: remove the `DoorCode` and its assignment.
- **Leave stale**: do nothing — the `DoorCode` remains but no longer matches hardware.
Recommendation: deactivate and flag, so the user can review. Deletion is destructive and loses audit history.

**15. `SyncResult` dataclass is never defined.**
The ADR says it contains "slots read, codes created, codes updated, conflicts, and errors" but doesn't define the shape. Proposed structure:
```python
@dataclass
class SyncResult:
    slots_total: int             # total occupied slots found
    codes_created: int           # new DoorCode records
    codes_updated: int           # existing records updated (sync-controlled fields changed)
    codes_deactivated: int       # previously-synced slots now empty
    conflicts: list[SyncConflict]  # slots where existing DoorCode differed
    errors: list[SyncError]      # per-slot read failures
    skipped_slots: list[int]     # e.g. slot 0 (master code)
    dismissed_slots: list[int]   # slots skipped due to sync_dismissed=True

@dataclass
class SyncConflict:
    slot_index: int
    door_code_id: int
    fields_overwritten: list[str]  # e.g. ["code_hash", "is_active"]

@dataclass
class SyncError:
    slot_index: int
    error: str                     # e.g. "WebSocket timeout reading userCode"
```

### Core sync flow gaps — DoorCode field defaults for synced codes

**16. `sync_lock_codes` function signature is incomplete.**
The ADR specifies `sync_lock_codes(lock_entity_id: str) -> SyncResult`. But `create_door_code()` requires `user` (FK) and uses `actor_user` for audit events. The sync function signature should be:
```python
def sync_lock_codes(
    *,
    lock_entity_id: str,
    target_user: User,       # owner for synced codes (finding 4)
    actor_user: User,         # admin who triggered sync (for DoorCodeEvent)
    zwavejs: ZwavejsGateway,  # protocol for testability
) -> SyncResult:
```

**17. `code_type` for synced codes is unspecified.**
Z-Wave JS has no concept of permanent/temporary/one_time/service. Default to `permanent` — Z-Wave user codes don't inherently expire by type.

**18. `is_active` mapping to Z-Wave slot status is undefined.**
CC 0x63 `userIdStatus` has several possible values. Required mapping:
- `Occupied/Enabled` (status 1) → `is_active=True`
- `Occupied/Disabled` (status 2) → `is_active=False`
- `Available` (status 0) → skip (empty slot, do not import)
- `StatusNotAvailable` (status 254) → include in `SyncResult.errors`, do not import

**19. Auto-generated labels for synced codes.**
`DoorCode.label` defaults to empty string. A list of synced codes all labeled `""` is unusable. The sync should generate labels like `"Slot 5"` or `"Synced Code (Slot 5)"`. On re-sync, the label is user-controlled and must not be overwritten (see finding 20).

**20. Sync-controlled vs user-controlled field split.**
The conflict resolution strategy must explicitly categorize every `DoorCode` field:

| Re-sync overwrites (sync-controlled) | Preserved on re-sync (user-controlled) |
|---|---|
| `user` (set to requested `user_id`) | `label` |
| `source`, `code_hash`, `pin_length` | `max_uses`, `uses_count` |
| `is_active` (from slot status) | `last_used_at`, `last_used_lock` |
| `code_type` (`permanent`/`temporary` based on schedule import) | `start_at`, `end_at` |
| `slot_index` (on assignment) | — |

Schedule fields are partially sync-controlled:
- `days_of_week`, `window_start`, `window_end` are imported when the lock exposes a representable `weekDaySchedule` (single window, same across selected weekdays).
- Unsupported schedules (year-day/daily repeating, multiple windows/day, different windows/day, midnight crossing) are not imported and existing schedule fields are preserved.
- `start_at` / `end_at` are not imported in v1.

### Zombie code prevention — dismissed-slot tracking

**21. Deleted synced codes must not reappear on re-sync.**
If a user syncs, deletes a synced code in LatchPoint, then re-syncs — the code would reappear because the slot is still occupied on the lock (push-sync is out of scope). This is a **core matching-logic concern**, not just a UX issue, because the matching strategy in finding 13 relies on `(lock_entity_id, slot_index)` lookups on `DoorCodeLockAssignment`. If the assignment is CASCADE-deleted along with the `DoorCode`, the matching logic has no memory that this slot was previously synced and dismissed.

**Solution:** When a user deletes a synced `DoorCode`, the delete handler sets `sync_dismissed=True` on the corresponding `DoorCodeLockAssignment` instead of (or in addition to) deleting it. On re-sync, assignments with `sync_dismissed=True` for the matching `(lock_entity_id, slot_index)` are skipped and reported in `SyncResult.dismissed_slots`. The user can clear the dismissal via the UI (e.g. a "Re-enable sync for this slot" action) if they change their mind.

This requires modifying the existing `delete_door_code()` use case: for synced codes, soft-mark the assignment rather than relying on CASCADE delete.

### Per-slot error handling

**22. Per-slot error strategy is unspecified.**
If reading 3 out of 30 slots fails (WebSocket timeout), does the whole sync fail or proceed with the 27 that succeeded? Given these are cache reads with low failure probability, the sync should use **best-effort with per-slot error reporting** — continue processing remaining slots and include failures in `SyncResult.errors`. The caller can decide whether to retry.

## Todos

### Model changes (migration)
- [x] Move `slot_index` to `DoorCodeLockAssignment` as `PositiveSmallIntegerField(null=True)` (finding 1).
- [x] Add `sync_dismissed` field (`BooleanField`, default `False`) to `DoorCodeLockAssignment` (finding 21).
- [x] Add `source` field (`CharField`, choices: `manual`/`synced`, default `manual`) to `DoorCode`.
- [x] Add conditional unique constraint on `DoorCodeLockAssignment(lock_entity_id, slot_index)` where `slot_index IS NOT NULL`.
- [x] Make `code_hash` nullable (`null=True, blank=True`) (finding 2).
- [x] Make `pin_length` nullable (finding 3).

### Design decisions (resolve before implementation)
- [x] Decide user ownership policy for synced codes (finding 4) — `user_id` is required on the API, selected via the existing owner selector in the UI.
- [x] Document Z-Wave value_id specifications for CC 0x63 (finding 5).
- [x] Define slot enumeration strategy — `node_get_defined_value_ids()` + per-slot reads for occupied slots (findings 7, 8).
- [x] Confirm `node_get_value()` return type for `userCode` and add normalization step (finding 9).
- [x] Define entity resolution: accept lock entity ID → extract `node_id` from registry → verify CC 0x63 support (findings 11, 12).
- [x] Define matching logic: match by `(lock_entity_id, slot_index)` only; no PIN-based dedup; document manual code behavior (finding 13).
- [x] Define disappeared-slot behavior — deactivate previously-synced codes when a slot is emptied (finding 14).
- [x] Define `SyncResult` dataclass shape (finding 15).
- [x] Define `sync_lock_codes` function signature with all required parameters (finding 16).
- [x] Default `code_type` to `permanent` (finding 17), `is_active` mapping per finding 18.
- [x] Auto-generate labels for synced codes — `"Slot {n}"` (finding 19).
- [x] Document sync-controlled vs user-controlled field split (finding 20).
- [x] Confirm best-effort per-slot error handling (finding 22).
- [x] Skip slot 0 (master code) — do not import (finding 10).
- [x] Implement dismissed-slot tracking in `delete_door_code()` for synced codes (finding 21).

### Implementation
- [x] Implement `locks/use_cases/lock_config_sync.py` with CC 0x63 queries, using `ZwavejsGateway` protocol.
- [x] Add `POST /api/locks/{lock_entity_id}/sync-config/` endpoint with error contract (404, 400, 503, 409, 403).
- [x] Add CC 0x63 capability check — verify node supports User Code CC before attempting sync.
- [x] Add frontend "Sync Codes from Lock" button, results dialog, synced-code badge, and "PIN unknown" indicator.
- [x] Modify `delete_door_code()` to soft-mark `sync_dismissed=True` on assignments for synced codes instead of CASCADE delete.
- [x] Address ADR 0069 items that must ship with the core sync (security, transactions, validation guard).

### Test scenarios (mocked Z-Wave JS gateway)
- [x] **First sync — multiple occupied slots**: some with exposed PINs, some with masked PINs → correct `DoorCode` + assignment creation, `code_hash=None` for masked.
- [ ] **Re-sync same lock — slot unchanged**: no new `DoorCode` created, no fields overwritten → idempotent no-op.
- [ ] **Re-sync — slot PIN changed**: `code_hash` updated on existing `DoorCode`, conflict recorded in `SyncResult.conflicts`.
- [ ] **Re-sync — slot emptied on lock**: existing `DoorCode` deactivated (`is_active=False`), reported in `SyncResult.codes_deactivated`.
- [ ] **Re-sync — new slot appeared**: new `DoorCode` created alongside existing synced codes.
- [ ] **Slot 0 (master code)**: skipped, reported in `SyncResult.skipped_slots`.
- [x] **Dismissed slot**: user deletes synced code, re-syncs → slot skipped, reported in `SyncResult.dismissed_slots`.
- [ ] **Node doesn't support CC 0x63**: endpoint returns 400 with clear error message.
- [ ] **Mid-sync WebSocket failure**: partial results returned with failed slots in `SyncResult.errors`.
- [x] **Concurrent sync**: second request returns 409 while first is in-flight.
- [ ] **PIN normalization**: `node_get_value()` returns int, bytes, or string → all coerced to string before hashing.
