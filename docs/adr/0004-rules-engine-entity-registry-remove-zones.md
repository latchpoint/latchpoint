# ADR 0004: Rules Engine + Entity Registry; Remove Zones

## Status
Proposed

## Context
The current system couples:
- “Import Sensors” (integration step) with
- alarm configuration (zones, entry behavior, active states).

This coupling blocks key capabilities:
- composing multiple entities with boolean logic (`AND`/`OR`/`NOT`) and nesting,
- time semantics like “A and B for 5 minutes”,
- using entities for multiple purposes (trigger vs disarm vs arm vs escalation),
- executing non-alarm actions (e.g., Home Assistant `call_service`).

Additionally, the concept of **Zones** is proving limiting for a rules-driven UX. Users want direct rule composition over entities and reusable grouping primitives (labels/tags/filters) rather than a fixed “zone” model baked into alarm logic.

## Decision
1) Introduce an **Entity Registry** as the integration boundary:
   - Import/sync from Home Assistant upserts local `Entity` records keyed by `entity_id`.
   - Import does not configure alarm behavior.

2) Introduce a **Rules Engine** as the configuration boundary:
   - Rules are defined as a versioned JSON AST with composable boolean logic and temporal operators (`FOR`, debounce/cooldown).
   - Rules can execute:
     - alarm actions (including **actually disarm**, including from `triggered`), and
     - Home Assistant actions via `call_service` with targets and service data.

3) Remove the **Zones** concept from product and data model:
   - Any remaining “grouping” is provided by tags/labels, saved filters, or device-class suggestions.
   - Existing zone-based setups are migrated into equivalent rules.

## Consequences
- Separation of concerns:
  - Import = integration + entity inventory
  - Rules = alarm logic + automation behaviors
- Significantly improved expressiveness:
  - `if (a or b or c) then trigger`
  - `if (a and b) for 5 minutes then disarm`
- Rules become the single place to define entity usage (trigger/disarm/arm/suppress/escalate/notify).
- Zones removal simplifies mental model but requires a migration plan and UI replacements for grouping.

Operational implications:
- Requires a rule evaluation engine, scheduling for `FOR` semantics, and audit logging.
- Adds responsibility for rate limiting/idempotency of HA service calls.

## Alternatives Considered
- Expand the current “Import Sensors” page to include rule composition and multi-purpose usage.
  - Rejected: continues to mix integration and configuration concerns; hard to scale UX.
- Keep Zones and add rules “within zones”.
  - Rejected: zones become an awkward intermediate abstraction for users who want direct logical composition.
- Hardcode rule columns in relational tables (no AST).
  - Rejected: schema churn and limited expressiveness; poor fit for nested logic.
- Use a string expression language (e.g., CEL) instead of JSON AST.
  - Deferred: powerful but harder to build a safe UI editor and explainability; AST is UI-friendly.

## Migration Notes
- Add `Entity` table and import/sync endpoints.
- Introduce `Rule` table and rule CRUD endpoints.
- Implement a minimal engine supporting:
  - boolean logic, `FOR`, cooldown,
  - alarm actions + HA `call_service`.
- Migrate existing Zone/Sensor configuration into generated rules.
- Deprecate Zones UI and then drop Zone model after stabilization.

## Todos
- Define Rule AST schema v1 (operators, node ids, schema versioning).
- Define conflict resolution policy (priority order, stop-after-fire).
- Implement explainability (evaluation trace) for UI debugging.
- Define HA service-call validation rules (security posture).
- Write admin-only Rules UI with simulate/explain tooling.

## References
- `docs/adr/0003-separate-entity-import-from-alarm-configuration.md`
- `docs/archived/RULES_ENGINE_PLANNING.md`
