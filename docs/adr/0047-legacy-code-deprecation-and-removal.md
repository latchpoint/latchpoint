# ADR 0047: Legacy Code Deprecation and Removal

## Status
**Implemented**

## Context
This codebase contains several "legacy" behaviors that exist primarily for backward compatibility:
- Compatibility facades and re-exports to keep old imports working.
- Deprecated settings keys and "legacy shape" serializers kept to avoid breaking older UI/API consumers.
- Protocol/event-parsing fallbacks to handle multiple upstream envelope formats.
- Compatibility wrappers for APIs that used to exist (or are expected by external callers) but are now replaced.

These are useful during migration periods, but they tend to accumulate and become hard to reason about:
- They increase maintenance cost and test surface area.
- They hide which interfaces are truly supported.
- They complicate refactors because call sites continue to depend on shims.

This app is still in active development and can tolerate breaking changes. In this phase, keeping legacy code "just in case"
usually slows iteration more than it helps.

We need a consistent way to document, track, and remove legacy code, and a default posture that prefers deletion over
long-term compatibility.

## Decision
Remove legacy/compatibility code paths by default (breaking changes are acceptable) and do removal work as a series of
small, reviewable PRs.

This ADR is intentionally action-oriented: it defines what we consider "legacy", identifies concrete targets, and sets a
removal checklist so we can delete code confidently without reintroducing new shims.

### 1) Definition
Code is considered **legacy** when it exists primarily to support:
- An older public API contract (HTTP/WS payload shape, settings keys, auth scheme).
- An older internal contract (imports/paths, module-level facades).
- An older upstream integration protocol/envelope.

### 2) Required markers (while it exists)
If we keep a legacy path temporarily, it must include:
- A clear marker: `Legacy:` or `Compatibility:` in a docstring or module header.
- A short rationale: what it supports and why it cannot be removed in the same PR.
- A removal condition: what must be true before it can be deleted (and how to validate it).
- A tracking reference and explicit "sunset" milestone/date.

### 3) Default placement and boundaries
Prefer isolating legacy behavior behind explicit boundaries so it is easy to find and remove:
- Compatibility facades live in a clearly named module (example: `backend/alarm/services.py`).
- Deprecated settings keys are handled in one place (settings registry + migration code), not scattered.
- Legacy API shapes should be serialized in dedicated serializers (and not leak into domain/use cases).
- Protocol fallbacks should be limited to parsing/normalization layers (not spread across business logic).

### 4) Removal criteria (minimum)
Legacy code should be deleted when:
- No internal call sites depend on it (validated by code search and/or tests).
- Any persisted-data dependency is handled (migration/backfill completed) if the legacy behavior touches stored data.

If the legacy path exists only to avoid breaking API clients, update those clients and remove the legacy path in the same
PR.

### 5) Removal checklist
When removing legacy code, do the following in the same PR when possible:
- Remove the shim and update all internal call sites.
- Remove or migrate any persisted compatibility data (settings keys, serialized shapes).
- Update API docs (and this ADR's candidate list) if relevant.
- Add/adjust tests to lock in the new contract and prevent reintroduction.

## Removal Targets
This section is the working inventory of concrete legacy code we intend to remove (or turn into a real supported API).
Each target should be handled by a dedicated PR unless it is trivial.

### Compatibility facades / re-exports
- ~~`backend/alarm/services.py`: compatibility facade for state machine operations.~~
  - **REMOVED**: All call sites rewritten to import directly from `alarm.state_machine.*`, `alarm.use_cases.*`, etc. `validate_user_code` moved into `alarm.use_cases.alarm_actions`.
- ~~`backend/alarm/serializers.py`: compatibility re-export wrapper.~~
  - **REMOVED** (prior to this ADR).

### Legacy API shapes / deprecated settings
- ~~`backend/alarm/serializers/alarm.py` `AlarmSettingsProfileSerializer`: legacy flat settings shape.~~
  - **REMOVED**: `AlarmSettingsView` switched to `AlarmSettingsProfileDetailSerializer`. Frontend adapter maps the `{ profile, entries }` response into the existing `AlarmSettingsProfile` type.
- ~~`backend/integrations_home_assistant/tasks.py`: supports deprecated `home_assistant_notify` settings key.~~
  - **REMOVED**: Entire file deleted. Notifications are now rules-driven via the consolidated Notifications architecture (ADR 0044).
- ~~`backend/alarm/state_machine/snapshot_store.py`: schedules Home Assistant notifications via the deprecated `home_assistant_notify` key.~~
  - **REMOVED**: `_schedule_home_assistant_notify()` deleted from `transition()`. The modern `alarm_state_change_committed` signal path remains.

### Integration compatibility
- ~~`backend/control_panels/zwave_ring_keypad_v2.py`: parses multiple legacy event envelopes.~~
  - **REMOVED**: Legacy `else` branch in `_extract_entry_control_notification()` removed. The gateway normalizes all events into `{"event": {...}}` format.
- ~~`backend/integrations_zwavejs/manager.py` `lock()` / `unlock()`: compatibility wrappers that are intentionally unimplemented.~~
  - **REMOVED** (prior to this ADR): Deleted from `ZwavejsConnectionManager`, `ZwavejsGateway` Protocol, and `DefaultZwavejsGateway`. No external callers existed.

### Data format compatibility
- ~~`backend/alarm/crypto.py`: plaintext pass-through for backward compatibility.~~
  - **REMOVED**: `encrypt_secret()` now raises `EncryptionNotConfigured` when no key is set. `decrypt_secret()` raises `ValueError` for plaintext values. A backfill command (`manage.py encrypt_plaintext_secrets`) is provided for migration. Save paths in views guard with `can_encrypt()` before storing.

## Execution Plan
- Start with internal-only shims (facades/re-exports) and update imports/call sites.
- Remove legacy API shapes next (serializer response shapes) and update frontend consumers accordingly.
- Remove deprecated settings keys after writing a one-time migration/backfill for existing profiles.
- Remove integration envelope fallbacks last, once gateways emit a single canonical shape.
- Treat crypto plaintext pass-through as a data migration task (needs a deliberate backfill and rollback plan).

## Alternatives Considered
- Keep handling legacy behavior case-by-case without a policy.
  - Rejected: removal becomes ad-hoc and hard to coordinate.
- Immediately delete all legacy code.
  - Rejected: would break current clients and/or persisted data assumptions.
- Maintain long-term backwards compatibility for all historical interfaces.
  - Rejected: indefinite complexity growth and unclear support boundaries.

## Consequences
- Legacy behavior becomes more visible and easier to delete safely.
- Slightly more process overhead when adding compatibility shims, offset by lower long-term maintenance.
- Clearer public/internal contracts and faster refactors once migrations complete.
