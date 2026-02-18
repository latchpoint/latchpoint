# ADR 0074: Test Suite Expansion Beyond Endpoint Baseline

## Status
Implemented

## Context
ADR 0073 closed a concrete set of backend endpoint coverage gaps and improved confidence around auth, response envelopes, and endpoint happy/error paths.

That baseline is necessary, but it does not fully cover higher-risk regressions that tend to appear in:
- async/realtime delivery paths (WebSocket + scheduler + outbox workers),
- permission drift across role-sensitive endpoints as features evolve,
- concurrency/idempotency behavior on mutating operations,
- integration fault mapping consistency (timeouts/unavailable/invalid config),
- cross-layer contracts (backend response shapes consumed by frontend flows).

This ADR defines the next useful set of tests after endpoint-baseline expansion.

## Decision
Adopt a phase-2 test expansion focused on behavior-level and operational regressions.

Priority test sets:
1. Permission matrix tests for sensitive API groups.
   - System config, integration settings/sync endpoints, debug endpoints, provider admin actions.
   - Explicit matrix: unauthenticated (`401`), authenticated non-admin (`403` where required), admin success.
2. Realtime and async contract tests.
   - WebSocket message contracts for initial snapshot, state updates, system-status updates, and error tolerance.
   - Notification outbox worker tests for retry/backoff progression and terminal states.
3. Concurrency and idempotency tests.
   - Repeated/distributed calls for arm/disarm/cancel-arming, profile activation, integration sync triggers.
   - Verify deterministic final state and absence of duplicate side effects.
4. Integration fault-mapping tests.
   - Ensure gateway/runtime exceptions map to stable ADR 0025 error envelopes and expected HTTP status codes.
   - Cover representative faults: invalid config, timeout, unavailable upstream, unexpected runtime error.
5. Cross-layer contract smoke tests.
   - High-value frontend-consumed API payload contracts (shape + required keys) locked via focused API tests.
   - Prevent backend response drift that silently breaks setup/settings/dashboard pages.

Scope note:
- This ADR extends ADR 0073 and does not supersede it.
- Keep tests deterministic by mocking gateways/runtime integrations and avoiding external network I/O.

## Alternatives Considered
- Continue adding endpoint tests only.
  - Rejected: leaves async/concurrency and role-matrix regressions under-covered.
- Move directly to broad end-to-end browser tests.
  - Rejected: useful later, but too slow/fragile to replace targeted deterministic backend coverage.
- Enforce full mutation/property testing now.
  - Rejected: high effort; phase-2 should prioritize practical risk reduction first.

## Consequences
- Moderate increase in test runtime and maintenance cost.
- Better confidence in production-like failure scenarios and async behavior.
- Lower regression risk in setup/settings flows that depend on stable backend contracts.

## Todos
- Added permission-matrix tests for role-sensitive endpoints in `backend/alarm/tests/test_permission_matrix_sensitive_api.py`.
- Extended websocket contract coverage in `backend/alarm/tests/test_websocket.py` for stricter payload/sequence assertions and connect-time error tolerance.
- Added outbox retry/backoff lifecycle boundary tests in `backend/notifications/tests/test_outbox.py` (max attempts, non-retryable terminal state, rate-limit backoff window).
- Added idempotency coverage in `backend/alarm/tests/test_idempotency_api.py` for repeated cancel-arming, repeated profile activation, and repeated entity sync upserts.
- Added integration fault-mapping tests in `backend/alarm/tests/test_integration_fault_mapping_api.py` for invalid-config, timeout, unavailable upstream, and unexpected runtime failures.
- Added grouped phase-2 runner `scripts/docker-test-phase2.sh`.

## Phase-2 Targeted Command
```bash
./scripts/docker-test-phase2.sh
```

## Acceptance Criteria
- Each priority test set has at least one implemented, deterministic test module.
- Role-sensitive endpoints in scope have explicit `401` / `403` / admin-success assertions.
- Realtime/async tests assert stable payload contracts and retry-state transitions.
- Concurrency/idempotency tests prove deterministic final state and no duplicate side effects for scoped flows.
