# ADR 0069: Lock Config Sync — Operational, Security & UX Concerns

## Status
**Partially Implemented** (core sync endpoint shipped; fast-follow items pending)

## Context
ADR 0068 defines the core sync flow for reading Z-Wave JS lock codes and schedules into LatchPoint's `DoorCode` model. During review, a number of valid concerns were identified that are **not about the core sync logic** (read → parse → match → create/update) but about the surrounding production-readiness of the sync endpoint.

These concerns are split into their own ADR so that ADR 0068 can focus on the sync data flow, and these items can be resolved incrementally — some before first implementation, some as fast-follows.

### Related ADRs
- **ADR 0068** — Z-Wave JS Lock Config Sync (core sync flow)
- **ADR 0057** — Integration Entity Updates Trigger Rules (dispatcher events)

## Decision
Address the following concerns as part of the lock config sync implementation, organized by category.

### Security

**1. Require `reauth_password` on the sync endpoint.**
Every existing door code mutation endpoint in `locks/views/door_codes.py` calls `assert_admin_reauth(request.user, reauth_password)` before making changes. The sync endpoint creates and modifies door codes — it must follow the same pattern.

**2. PIN exposure risk in SyncResult and event metadata.**
If the lock firmware exposes raw PINs via CC 0x63, the sync function will receive them in plaintext. Requirements:
- PINs must be hashed immediately via `make_password()` (matching `door_codes.py:117`).
- Raw PINs must **never** appear in `SyncResult`, API responses, `DoorCodeEvent.metadata`, or log output.

### Concurrency & transaction safety

**3. Race condition on concurrent sync triggers.**
Nothing prevents two admins (or a double-click) from firing `POST /api/locks/{id}/sync-config/` simultaneously. The unique constraint on `(lock_entity_id, slot_index)` prevents duplicate *assignments*, but two concurrent syncs could each create separate `DoorCode` records for the same slot before the assignment insert triggers the constraint violation. Options:
- Per-lock advisory lock / `select_for_update()` at the start of the use case.
- Return 409 if a sync for this lock is already in-flight (lightweight guard).

**4. Transaction boundary for the batch operation.**
The sync is a batch operation that may create/update dozens of codes. If it creates 20 codes and fails on the 21st, partial state remains with no rollback. The entire `sync_lock_codes` use case must be wrapped in `@transaction.atomic`.

### Synced code UX

**5. Zombie codes on deletion-then-re-sync.**
The core matching-logic fix for this is now in **ADR 0068 (finding 21)**: `DoorCodeLockAssignment` gains a `sync_dismissed` field, and `delete_door_code()` soft-marks assignments for synced codes instead of CASCADE-deleting them. Re-sync skips dismissed slots.

The remaining **UX concerns** for this ADR:
- The UI should show dismissed slots somewhere (e.g. a "Dismissed synced slots" section on the lock detail page) so users can re-enable sync for a slot if they change their mind.
- The sync results dialog should report dismissed slots that were skipped.

**6. Editing rules for synced codes.**
Which fields can a user edit on a synced code? If they change `label` and then re-sync, the label should be preserved (user-controlled). But `is_active` should be overwritten from slot status. These rules are defined in ADR 0068 (sync-controlled vs user-controlled field split) but the UI must enforce them — e.g. disable editing of sync-controlled fields, or show a warning.

**7. `validate_door_code()` must handle `code_hash=None`.**
`validate_door_code()` in `code_validation.py:40-97` calls `check_password(raw_code, candidate.code_hash)`. If `code_hash` is `None` (masked PIN on a synced code), this crashes. The validation path must skip or short-circuit synced codes with unknown PINs. This is a pre-requisite for the sync feature — if synced codes exist in the DB, validation must not break.

### Frontend

**8. UI button naming collision.**
The frontend already has a "Sync Z-Wave" button (`DoorCodesPage.tsx:88`) wired to `useSyncZwavejsEntitiesMutation` for entity registry sync. Adding a code sync button needs a clearly distinct label — e.g. "Sync Codes from Lock" vs the existing "Sync Z-Wave" (entity sync).

**9. Lock selector for multi-lock scenarios.**
The sync operates on a single lock. If the user has multiple Z-Wave locks, the UI needs either a lock picker in the sync dialog, or per-lock sync buttons in a lock list view.

**10. Sync-in-progress feedback.**
The sync is slow for two reasons: ~2 WebSocket round-trips per occupied slot, and `make_password()` PBKDF2 hashing per imported PIN (~0.2–0.3s each). For a lock with 30 occupied slots, total sync time is 15–40 seconds. The frontend should show a loading spinner with indeterminate progress. For v1, a long-timeout POST with a spinner is sufficient.

### Operational

**11. `ensure_connected()` guard.**
The existing `AvailableLocksView` calls `ha_gateway.ensure_available()` before querying. The sync endpoint should call `zwavejs.ensure_connected()` and return 503 if Z-Wave JS is not connected. This follows the pattern in `ZwavejsEntitySyncView`.

**12. No "last synced" timestamp.**
There's no way to see when a lock was last synced. Consider storing `last_synced_at` per lock — either in a new `LockSyncState` model, or in `Entity.attributes` metadata. The frontend can display "Last synced: 5 minutes ago."

**13. Stale entity IDs after Z-Wave re-inclusion.**
If the user re-includes their Z-Wave stick (new `home_id`), all `zwavejs:*` entity IDs change because `home_id` is part of the entity ID format. Synced `DoorCodeLockAssignment` records become orphaned. This is a known limitation — a re-sync after re-inclusion will create new assignments. Old orphaned assignments can be cleaned up manually or by a future migration.

**14. No dispatcher event for downstream rules.**
ADR 0057 establishes that integration entity updates trigger rules via the dispatcher. When codes are synced, a `door_code_synced` signal could fire so rules can react (e.g. "notify me when a new code appears on the lock"). The sync currently records `DoorCodeEvent` for audit but doesn't emit dispatcher events. This is a nice-to-have for v1.

### Enhancements

**15. Dry-run mode.**
Add a `?dry_run=true` query parameter that returns the `SyncResult` (what would be created/updated/conflicted) without persisting any changes. This is cheap to implement — skip DB writes inside the same use case function — and gives users confidence before committing. Especially valuable given the zombie code concern (finding 5).

**16. `code_synced` event type already exists.**
`DoorCodeEvent.EventType.CODE_SYNCED` is already defined at `locks/models.py:111`. No new event type is needed — just reference the existing one.

## Consequences
- These items add implementation surface beyond the core sync flow.
- Items 1–2 (security) and 3–4 (concurrency) and 7 (validation crash) should be addressed in the same PR as the core sync, since they affect correctness.
- Item 5 (zombie codes): the core matching-logic fix (`sync_dismissed` field, soft-delete on assignment) is now part of **ADR 0068**. The remaining UX work (dismissed-slot UI, re-enable action) can be addressed iteratively here.
- Items 6 (editing rules) and 8–10 (frontend) can be addressed iteratively.
- Items 11–16 (operational + enhancements) are nice-to-haves for v1.

## Todos

### Must ship with core sync (same PR)
- [x] Require `reauth_password` on the sync endpoint (finding 1).
- [x] Hash PINs immediately; never store raw PINs in responses, events, or logs (finding 2).
- [x] Wrap `sync_lock_codes` in `@transaction.atomic` (finding 4).
- [x] Add concurrency guard — per-lock advisory lock or 409 for in-flight syncs (finding 3).
- [x] Guard `validate_door_code()` against `code_hash=None` for synced codes (finding 7).
- [x] Call `zwavejs.ensure_connected()` before sync; return 503 if disconnected (finding 11).

### Should ship with core sync (UX)
- [x] Use distinct button label "Sync Codes from Lock" (not "Sync Z-Wave") (finding 8).
- [x] Add lock selector for multi-lock scenarios (finding 9).
- [x] Show loading spinner during sync (finding 10).

### Fast-follow
- [ ] Add UI for dismissed synced slots — show dismissed slots, allow re-enabling sync per slot (finding 5; core matching logic is in ADR 0068).
- [ ] Enforce editing rules for synced vs manual codes in the UI (finding 6).
- [ ] Store `last_synced_at` per lock (finding 12).
- [ ] Document stale entity ID behavior after Z-Wave re-inclusion (finding 13).

### Future enhancements
- [ ] Emit dispatcher events on code sync for rules integration (finding 14).
- [ ] Add `?dry_run=true` query parameter (finding 15).
