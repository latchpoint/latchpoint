# ADR 0015: Integration Signals Contract

## Status
**Implemented**

## Context
ADR 0014 establishes a “core + integrations as separate Django apps” architecture and uses Django signals for the core → integrations boundary.

Signals are easy to grow into an implicit, unstable API if we do not define:
- which signals exist,
- what arguments they carry,
- when they fire (transaction semantics),
- and what reliability guarantees integrations can assume.

This ADR defines the contract so new integrations can be implemented without coupling to internal core modules.

## Decision
The following signals are the stable integration boundary and must remain backwards compatible (additive changes only) unless superseded by a new ADR.

### `alarm.signals.alarm_state_change_committed`
- **When**: fired via `transaction.on_commit()` after an alarm state transition is successfully persisted.
- **Args (keyword-only)**:
  - `state_to: str`
- **Guarantees**:
  - Fired at most once per committed transition.
  - Never fired for rolled-back transitions.
- **Non-guarantees** (best-effort):
  - Delivery is in-process only; no persistence/retry.
  - Handler execution order is undefined.
  - Handler failures must not affect the core transition; exceptions should be caught in handlers.

### `alarm.signals.settings_profile_changed`
- **When**: fired via `transaction.on_commit()` after the active settings profile is activated, or after entries are updated for a profile.
- **Args (keyword-only)**:
  - `profile_id: int`
  - `reason: str` (current values: `"updated"` or `"activated"`)
- **Guarantees**:
  - Fired only after the DB commit that makes the change visible.
- **Non-guarantees** (best-effort):
  - Delivery is in-process only; no persistence/retry.
  - Integrations must re-read state from DB and handle missing/invalid settings defensively.

### Handler rules (for all integrations)
- Handlers should be **fast** and **best-effort**:
  - For network IO or heavy work, queue a Celery task (preferred) or do minimal publish operations with timeouts.
- Handlers must be **idempotent** where practical:
  - repeated calls should not cause incorrect state (publishing retained MQTT discovery/state is OK).
- Integrations must not rely on signal handlers to enforce core business rules.

## Alternatives Considered
- Direct calls from core into integration modules.
  - Rejected: creates hard imports and circular dependencies.
- A central registry/dispatcher app with manual registration.
  - Rejected: more moving parts than necessary for “normal Django apps”.
- Outbox/event table with reliable delivery.
  - Deferred: valuable for reliability, but higher complexity than required right now.

## Consequences
- Clear, documented integration boundary that remains stable across refactors.
- Integrations are decoupled from core internals and can evolve independently.
- Signals remain best-effort and in-process; reliable delivery requires explicit tasking/outbox patterns.

## Todos
- If we need stronger guarantees, add an “integration outbox” ADR and migrate critical events to it.

