# ADR 0021: Rules Engine “THEN” Actions

## Status
**Partially Implemented** (executor + audit logging exist; typed `definition.then` validation and HA/Z-Wave permissions/allowlists pending)

## Context
The rules engine already supports evaluating conditions (`definition.when`) and executing internal “then” actions, but the “THEN” concept is not yet treated as a stable, documented contract across API + UI.

Examples we want to support:
- If a motion/contact/verification condition triggers, **turn on a Home Assistant light**.
- If a high-severity condition triggers, **trigger the alarm** so connected control panels (e.g., Ring Keypad v2) can react via existing integration hooks (state changes, tones, etc).

Constraints:
- Core code must not import integration implementations directly (ADRs 0007, 0014, 0015).
- Actions can cause side effects; we need clear validation, auditing, and a security posture (ADR 0010).
- Rules must remain testable without requiring real Home Assistant / Z-Wave JS connections.

## Decision
We add an explicit “THEN” actions list to the rule definition schema:

- `Rule.definition.when`: existing condition AST.
- `Rule.definition.then`: an ordered list of action objects executed when the `when` condition is satisfied and cooldown/`for` semantics allow firing.
- `Rule.schema_version`: versions the `Rule.definition` schema (including `when` + `then`); action objects do not carry their own version.

### Action execution boundary
- The rules engine remains orchestrator-only (`alarm.rules_engine.run_rules()`); it delegates action execution to `alarm.rules.action_executor.execute_actions()`.
- The executor depends on **Protocols/gateways**, not integration modules:
  - Alarm transitions go through the alarm services/use-case facade.
  - Home Assistant side effects go through `HomeAssistantGateway`.
  - Z-Wave JS value writes go through `ZwavejsGateway`.
- Integrations and devices (e.g., Ring Keypad v2) react to alarm state changes through the existing signals contract (ADR 0015) rather than being directly invoked from core rule logic.

### Supported action types (initial set)
We standardize on action objects shaped like `{ "type": "<action_type>", ... }` and support:
- `alarm_trigger` / `alarm_arm` / `alarm_disarm`: transition the alarm state machine.
- `ha_call_service`: call a Home Assistant service (e.g., `light.turn_on`) with optional `target` and `service_data`.
- `zwavejs_set_value`: write a Z-Wave JS value by `node_id` + `value_id` (advanced / admin-only use; e.g., device-specific keypad tones).

#### Action schemas (schema_version=1)
We treat the following as the canonical, versioned action shapes within `Rule.definition.then`:

- `alarm_trigger`: `{"type":"alarm_trigger"}`
  - No parameters (severity/options are expressed by rule kind/priority and future action extensions).
- `alarm_disarm`: `{"type":"alarm_disarm"}`
  - No `code` parameter (automations should not store PINs; actions rely on the authenticated actor and audit trail).
- `alarm_arm`: `{"type":"alarm_arm","mode":"armed_home"}`
  - `mode` is the target alarm state (e.g., `armed_home`, `armed_away`).
- `ha_call_service`: `{"type":"ha_call_service","action":"light.turn_on","target":{...},"data":{...}}`
  - `action` is a required string in `domain.service` format (e.g., `light.turn_on`, `lock.lock`).
  - `target` and `data` are optional objects.
  - This format matches Home Assistant's 2024.8+ "actions" terminology where services are now called actions.
- `zwavejs_set_value`: `{"type":"zwavejs_set_value","node_id":12,"value_id":{...},"value":...}`
  - `node_id` (int) and `value_id` (object) are required.
  - `value_id.commandClass` (int) and `value_id.property` (string or int) are required; `value_id.endpoint` (int) defaults to `0`; `value_id.propertyKey` (string or int) is optional.
  - `value` is the value to write (type depends on the target value ID).

### Validation + security posture
- Rule creation/update must validate that `definition.then` is a list of objects and that each action matches its required schema for the active `schema_version`.
- `ha_call_service` must be constrained by an allowlist (domain/service and target semantics) and be **admin-only** to prevent arbitrary HA side effects.
- `zwavejs_set_value` must be **admin-only** (advanced escape hatch; it can create unexpected device side effects).
- Action execution is best-effort per action (one action failing does not prevent later actions from being attempted), and the result is fully recorded.

### Auditability
Every rule fire records:
- rule + timestamp
- the `then` actions attempted
- per-action results (success/error)
- pre/post alarm state (when relevant)

## Alternatives Considered
- Keep rules “pure” and rely on Home Assistant automations for side effects.
  - Works, but splits behavior across systems and makes the alarm panel’s rules less useful as the central automation surface.
- Allow arbitrary Python/code execution as “actions”.
  - Too dangerous and untestable; impossible to secure in a multi-user/admin UI.
- Add a generic webhook action only.
  - Simple, but pushes complexity to external glue and loses typed validation and UX affordances.

## Consequences
- Rules become a complete “IF/THEN” automation surface within the alarm panel, enabling first-class HA + alarm behaviors.
- The action schema becomes an API contract that requires versioning discipline (`schema_version`) and migration tooling if/when it evolves.
- We must maintain a clear security posture (allowlists + permissions) to avoid turning the rules engine into an arbitrary remote-control API for HA/Z-Wave.

## Future Ideas
- “ELSE” / “ELSE IF” branching (explicit, typed; no implicit negation hacks).
- Action groups: `sequence` / `parallel`, `delay`, and `repeat` (with guardrails).
- Templates/variables (limited string interpolation) for HA service data.
- First-class actions:
  - notifications (push, HA notify, SMS/email),
  - media/TTS announcements,
  - scenes/scripts execution,
  - MQTT publish (via transport),
  - webhook calls (with allowlist + timeouts),
  - “ring keypad tone / beep” action built on `zwavejs_set_value` but wrapped in a safe, device-specific schema (see ADR 0020).
- Reliability patterns for side effects: retries/backoff, idempotency keys, and an outbox/job queue for critical actions.
- Rule-level and action-level rate limiting and per-target cooldowns (beyond a single rule cooldown).

## Todos
- Implementation status: executor + audit logging exist; typed `definition.then` validation and HA/Z-Wave permissions/allowlists are still pending.
- Define and document the canonical action schemas (including examples) in user-facing docs.
- Add backend validation errors that are field-specific and UI-friendly for `definition.then`.
- Enforce a security posture for side-effecting actions:
  - `ha_call_service` allowlist (domain/service and target semantics)
  - permissions (admin-only) for HA/Z-Wave side effects
- Add a “supported actions” discovery endpoint for the frontend rule builder (for typed UX + allowlist-driven options).
- Add tests for:
  - action schema validation
  - HA allowlist enforcement
  - audit log content for successful and failing actions
- Add frontend UI to build and edit `then` actions:
  - Home Assistant light example: `{"type":"ha_call_service","action":"light.turn_on","target":{"entity_id":["light.kitchen"]}}`
  - Lock doors example: `{"type":"ha_call_service","action":"lock.lock","target":{"entity_id":["lock.front_door","lock.back_door"]}}`
  - Alarm trigger example: `{"type":"alarm_trigger"}`
