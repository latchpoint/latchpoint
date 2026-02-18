# ADR 0073: Backend Endpoint Test Baseline Expansion (Useful Gaps)

## Status
Proposed

## Context
The backend test suite is strong in core domains (state machine, rules engine, integrations, scheduler), but some HTTP endpoints still lack direct API coverage.

A recent inventory of URL names versus `reverse(...)` usage in backend tests identified the remaining endpoint-focused gaps:
- `dispatcher-status`
- `dispatcher-config`
- `dispatcher-suspended-rules`
- `mqtt-status`
- `zigbee2mqtt-status`
- `zigbee2mqtt-devices`
- `zigbee2mqtt-devices-sync`
- `provider-list`
- `provider-detail`
- `provider-test`
- `provider-types`
- `log-list`
- `pushbullet-devices`
- `pushbullet-validate-token`
- `ha-services`
- `ha-system-provider-test`

The same inventory also showed `alarm-rules-supported-actions` is tested with a hardcoded URL path, not `reverse(...)`, and does not have explicit unauthenticated coverage.

ADR 0067 already documented endpoint coverage gaps at a high level. This ADR does not supersede ADR 0067; it narrows to a concrete phase-1 implementation baseline and test contract.

## Decision
Adopt a phase-1 backend endpoint baseline focused on high-value API coverage gaps.

For each endpoint in scope, add:
- auth smoke test (`401` when unauthenticated),
- happy-path test (status code and essential response shape),
- at least one representative error-path test for integration-backed or mutating endpoints.

Additional test contract decisions:
- Use `reverse("<url-name>")` in endpoint tests instead of hardcoded paths.
- Assert standardized response contracts:
  - success payloads rendered under ADR 0025 envelope (`{"data": ...}`),
  - error payloads rendered as standardized `{"error": {...}}`.
- Keep tests deterministic by patching gateways/handlers/runtime helpers (no external network I/O).

Phase-1 priority areas:
1. Dispatcher API endpoints (`dispatcher-*`).
2. MQTT transport status endpoint (`mqtt-status`).
3. Zigbee2MQTT status/devices/sync endpoints.
4. Notifications HTTP API endpoints (providers, types, logs, Pushbullet helpers, HA helper endpoints).
5. Harden supported-actions endpoint coverage (`alarm-rules-supported-actions`) with explicit unauthenticated and `reverse(...)`-based tests.

## Alternatives Considered
- Keep ADR 0067 only and add tests ad hoc.
  - Rejected: easy to lose execution focus and acceptance criteria.
- Require immediate 100 percent endpoint coverage.
  - Rejected: too expensive for active development churn.
- Focus only on domain/unit tests.
  - Rejected: endpoint auth/permissions/envelope regressions are specifically HTTP-layer risks.

## Consequences
- Backend test count and runtime increase modestly.
- Better protection for auth/permissions and response-shape regressions.
- Clear, auditable endpoint baseline that can be extended incrementally in later ADRs.

## Todos
- Add `backend/alarm/tests/test_dispatcher_api.py` for dispatcher status/config/suspension endpoints.
- Add `backend/transports_mqtt/tests/test_mqtt_status_api.py` for `mqtt-status`.
- Add endpoint-focused Zigbee2MQTT API tests (new file or extension of `backend/alarm/tests/test_zigbee2mqtt_api.py`) for status/devices/sync.
- Add `backend/notifications/tests/test_api.py` for provider/types/logs/pushbullet/HA helper endpoints.
- Extend supported-actions API tests to:
  - use `reverse("alarm-rules-supported-actions")`,
  - assert unauthenticated request returns `401`.
- Validate with `./scripts/docker-test.sh`.
- After implementation, update this ADR status to `Implemented` and update `docs/adr/0000-adr-index.md`.

## Acceptance Criteria
- All phase-1 tests are present and passing in backend CI/local docker test flow.
- Each scoped endpoint has auth and happy-path coverage.
- Integration-backed endpoints include at least one deterministic failure-path assertion.
- Endpoint tests in scope use URL names (`reverse`) rather than hardcoded API paths.
