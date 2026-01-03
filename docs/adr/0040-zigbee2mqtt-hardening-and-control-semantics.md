# ADR 0040: Zigbee2MQTT Hardening (Validation, Ingest Mapping, Alarm Control Semantics)

## Status
Superseded by ADR 0049

Note: this ADR references legacy `output_mappings`, which has since been removed in favor of rules-driven Zigbee2MQTT control (ADR 0049).

## Context
ADR 0018 (Zigbee2MQTT integration) is implemented and usable:
- profile settings + admin UI
- entity import/sync
- runtime ingest and best-effort mapping refresh
This ADR originally included alarm control via action events guarded by a panel code. That functionality was removed to keep Zigbee2MQTT aligned with the other integrations and to avoid shipping an untestable control path.

As we move from “MVP works” to “operator safe”, there are a few decisions to lock down so behavior stays consistent and testable:
- How mapping validation is enforced (client vs server vs both).
- How ingest maps payload keys to entity IDs without excessive DB churn or incorrect updates.
ADR 0049 replaces the overall approach by leaning on entities + the rules engine (no special Zigbee keypad/panel control).

## Decision

### 1) Keep server-side validation on save (optional “validate-only” later)
Validation for Zigbee2MQTT settings (especially `output_mappings`) is enforced server-side on:
- `PATCH /api/alarm/integrations/zigbee2mqtt/settings/`

If the UI needs “validate without saving”, we may add a dedicated endpoint later:
- `POST /api/alarm/integrations/zigbee2mqtt/validate/` (optional)

**Why**
- This is already a single source of truth (DRF serializers) and protects against stale client-side validation.
- A separate endpoint is only worth it for UX (draft validation) and should not duplicate business rules.

### 2) Update only known entity IDs during ingest (avoid “best-effort” updates)
Device sync already stores enough information under `Entity.attributes` (including Zigbee2MQTT `ieee_address` and expose/property metadata) to derive the exact entity IDs that exist for a device.

Runtime ingest should:
- continue to use a cached `friendly_name -> ieee_address` mapping to associate topic → device,
- maintain a cache of “known entity IDs for this device” (per `ieee_address`, and optionally per profile/base_topic),
- update only those known entity IDs (and skip unknown keys entirely).

**Why**
- Reduces DB write amplification.
- Avoids accidental updates to the wrong entity IDs.
- Makes ingest behavior predictable, which improves troubleshooting and tests.

### 3) Route Zigbee alarm control through use cases (policy parity)
When processing configured Z2M input mappings (keypad/button events), call alarm transitions through a dedicated use case instead of direct `alarm.services.*` calls.

Introduce a dedicated “integration-originated alarm action” use case that:
- validates the Zigbee panel code semantics (separate from user PIN codes),
- applies coarse rate limiting (shared semantics, not per-integration ad-hoc),
- records audit metadata (source=`zigbee2mqtt`, ieee/friendly_name, action),
- delegates to `alarm.use_cases.alarm_actions.arm_alarm` / `disarm_alarm` (and adds a comparable use case for cancel-arming if needed).

**Why**
- Keeps alarm control behavior consistent across HTTP, HA-MQTT, and Zigbee2MQTT.
- Minimizes divergence in security-sensitive code paths.

## Alternatives Considered
- Client-only validation.
  - Rejected: drift risk and no protection for non-UI callers.
- Keep current “best-effort” entity updates.
  - Rejected: too easy to become noisy and incorrect as device payloads vary.
- Keep direct `services.*` calls for Zigbee control.
  - Rejected: increases the chance of policy divergence (code requirements, rate limiting, audit).

## Consequences
- Server-side validation stays centralized; any “validate-only” endpoint is optional and should remain a thin wrapper over existing serializers.
- Ingest becomes more correct and cheaper by skipping unknown keys, at the cost of maintaining a small “known entity IDs” cache.
- Zigbee alarm control becomes easier to audit and reason about by aligning with use-case patterns.

## Todos
- (Optional) Add `POST /api/alarm/integrations/zigbee2mqtt/validate/` and tests for it (draft validation UX).
- (Optional) Expand docs (`docs/ZIGBEE2MQTT.md`) with additional mapping examples once the schema is stable.
