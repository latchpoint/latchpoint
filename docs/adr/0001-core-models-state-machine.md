# ADR 0001: Core Models and State Machine (MVP)

## Status
**Implemented**

## Context
We need a minimal, durable data model and alarm state machine to support Phase 1.

## Decision
- Use a single "current state" row (AlarmStateSnapshot) and rely on AlarmEvent for history.
- Do not add a separate AlarmTransition table; encode transitions in AlarmEvent state_from/state_to.
- Multiple sensor triggers during pending do not change state; log each trigger as an AlarmEvent.
- Store exact previous armed state in AlarmStateSnapshot.previous_state for deterministic return.
- Non-entry sensors trigger immediately (`armed_* -> triggered`), entry sensors go to `pending`.
- If triggered while `arming`, return to the intended `target_armed_state`, not `arming`.
- Snapshot effective timing at arm time to avoid mid-session settings changes.
- Zone entry delay overrides apply only to entry-point sensors.
- Enforce per-code lockout plus a global rate limit (per user/device/IP).
- Define code_type permissions: master can always disarm/override, admin can arm/disarm + manage codes, user can use own code for arm/disarm.

## Alternatives Considered
- Append-only state history table with a "current" pointer for richer audit.
- Separate transition table for explicit state changes.
- Aggregate sensor triggers into a single pending event or extend pending timer.
- Infer previous armed state from last event rather than storing on snapshot.
- Treat all sensors as entry-delayed regardless of entry-point flag.
- Return to `arming` after trigger-time when triggered during arming.
- Dynamically use mutable settings profile values mid-session.
- Apply zone delay overrides to any sensor in the zone.
- Only per-code lockouts without global rate limiting.
- Keep code_type enum without explicit permissions.

## Consequences
- Keeps MVP schema lean and simpler to implement.
- AlarmEvent becomes the primary audit trail for state transitions.
- Pending state behavior is stable; extra triggers remain observable in logs.
- Snapshot must be updated transactionally to avoid drift.
- Immediate trigger for non-entry sensors reduces false delays but increases sensitivity.
- Target armed state must be persisted when arming begins.
- Timing behavior remains predictable even if settings change mid-session.
- Entry delay logic becomes deterministic and tied to entry-point sensors.
- Rate limiting logic must be implemented at the API/auth layer.
- Permission enforcement must be explicit in service/command handlers.

## Todos
- Re-evaluate if a state history table is needed after Phase 1.
- Confirm if pending behavior should change with future requirements (e.g., escalation).
