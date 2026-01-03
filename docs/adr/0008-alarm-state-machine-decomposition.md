# ADR 0008: Alarm State Machine Decomposition + Services Facade

## Status
**Implemented**

## Context
`alarm.services` had grown into a large module mixing:
- state machine transitions (arm/disarm/pending/triggered timers),
- snapshot persistence/locking,
- timing calculation and overrides,
- event/audit recording,
- user-code validation (via accounts).

This violates SRP and makes changes riskier because unrelated concerns live in the same file.

## Decision
- Introduce `alarm.state_machine` package with focused modules:
  - `constants.py` (armed state set)
  - `errors.py` (transition and code-related errors)
  - `settings.py` (active settings profile lookup)
  - `timing.py` (timing resolution + snapshot timing extraction)
  - `events.py` (event/audit persistence)
  - `snapshot_store.py` (snapshot locking + transition persistence)
  - `transitions.py` (state machine operations)
- Keep `alarm.services` as a compatibility facade that re-exports the public API used by views/tests, and retains `validate_user_code()` as a wrapper so existing tests that patch `alarm.services.timezone.now` remain stable.

## Alternatives Considered
- Leave `alarm.services` as-is and rely on conventions/comments to manage complexity.
- Move everything into `alarm.use_cases` (would blur “domain state machine” vs “application orchestration”).
- Replace with a full domain-layer architecture (ports/adapters, aggregates) immediately (too big a leap).

## Consequences
- Smaller, more focused modules with clearer ownership.
- Lower risk refactors: timing changes don’t touch event logging; persistence changes don’t touch condition logic.
- Existing imports (`from alarm import services`) continue to work.

## Todos
- Incrementally migrate new call sites to import from `alarm.state_machine` directly.
- Consider moving code-usage events (`record_failed_code`/`record_code_used`) fully into accounts/application layer if the domain boundary changes.

