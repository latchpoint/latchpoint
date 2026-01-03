# Rules Engine + Entity Registry Planning

> Archived: implemented and/or superseded; kept for historical context.

## Intent
Replace the current “import sensors” + zone-based configuration with a rules-first system:
- Import = sync Home Assistant entities into a local **Entity Registry**.
- Configuration = create **Rules** that decide how entities are used (trigger/disarm/arm/suppress/escalate/notify) using boolean logic and time semantics.
- Actions can directly change alarm state (including **actually disarm**) and can also **call Home Assistant services**.
- Remove the concept of **Zones** from the product and data model.

This planning doc focuses on rule capabilities, data model shape, APIs, UI, evaluation semantics, and migration steps.

---

## Product Goals
- Powerful composable conditions: `AND` / `OR` / `NOT`, nested groups.
- Time semantics:
  - Sustained truth: `FOR 5 minutes` (continuous).
  - Optional later: `WITHIN 5 minutes` windows and ordered sequences.
  - Debounce and cooldown to prevent flapping/spam.
- Rule actions:
  - Alarm actions: `DISARM`, `ARM(mode)`, `PENDING(entry_delay)`, `TRIGGER`, `SET_BYPASS`.
  - Home Assistant actions: `call_service(domain, service, target, service_data)`.
- Deterministic rule evaluation with priorities and clear conflict resolution.
- Auditability: every rule-fired action is logged, traceable, explainable.
- Safety and permissions: rules are admin-managed; rule execution is idempotent and rate-limited.

---

## Terminology
- **Entity**: a Home Assistant entity (e.g. `binary_sensor.front_door`, `sensor.temperature_kitchen`).
- **Entity Registry**: local table of imported entities and their last-known state/attributes.
- **Rule**: a record containing a versioned JSON definition with `WHEN` (conditions) and `THEN` (actions), plus guards and execution policy.
- **Condition AST**: a tree structure representing nested boolean/time constraints.
- **Action**: a side effect (alarm state transition, HA service call, etc.).

---

## Rule Types (Kinds)
At minimum (v1):
- **Trigger Rule**: when matched, puts alarm into `PENDING` or `TRIGGERED`.
- **Disarm Rule**: when matched, **disarms** (including from `TRIGGERED`).
- **Arm Rule**: when matched, arms into a chosen mode (away/home/night/vacation).
- **Suppress Rule**: prevents triggers (bypass/ignore inputs temporarily).
- **Escalation Rule**: chained actions after trigger/pending (siren, notify, lights).

Optional (v2):
- **Notify Rule** (if not covered by “HA call_service notify”).
- **Policy Rule** (limits when other rules are allowed to run).

---

## Conditions: Building Blocks

### Boolean composition
- `ALL` (AND)
- `ANY` (OR)
- `NOT`
- Nesting: arbitrary depth.

### Entity predicates
- State equals / not equals:
  - examples: `binary_sensor.front_door == 'on'`, `lock.front_door == 'unlocked'`
- Numeric comparisons (derived from state or attribute):
  - `sensor.temp_kitchen > 60`
- Attribute comparisons:
  - `binary_sensor.front_door.attributes.device_class == 'door'`
  - battery, tamper, motion class, etc.
- Availability:
  - is `unavailable` / `unknown`

### Alarm predicates (guards can also cover these)
- Alarm is in state(s): `armed_away`, `pending`, `triggered`, etc.
- Alarm timing context (entry delay running, exit delay running).

### Schedule predicates
- Time windows (daily, weekdays, custom ranges).
- “Quiet hours” guards for escalations/notifications.

### Temporal operators
v1 must include:
- `FOR duration`: condition must remain true continuously for duration.
- `COOLDOWN duration`: rule (or action) can only fire once per duration.
- `DEBOUNCE duration`: require stability before treating a change as true.

v2 candidates:
- `WITHIN duration`: e.g. “A then B within 5 minutes”.
- “count of events within window” (e.g. 3 motions in 2 minutes).

---

## Actions: What Rules Can Do

### Alarm actions (core)
- `DISARM` (explicitly allowed from any armed/pending/triggered state)
- `ARM` with mode (`armed_home`, `armed_away`, etc.)
- `SET_STATE` variants:
  - `PENDING` with entry delay override (optional)
  - `TRIGGERED` (immediate trigger)
- `BYPASS` / `SUPPRESS`:
  - bypass a specific entity for duration
  - bypass “all triggers” for duration (maintenance mode)

### Home Assistant service calls
- `CALL_HA_SERVICE`:
  - `domain`, `service`
  - `target` (entity_ids, device_ids, area_ids)
  - `service_data` (JSON)
- Templating (restricted/safe subset, optional v1):
  - allow referencing `{{ alarm.state }}`, `{{ entity('binary_sensor.front_door').state }}`, `{{ now }}`.

### Execution policy
- Per rule: whether to continue evaluating lower-priority rules after firing.
- Per action: whether to stop after first successful action.

---

## Data Model (Proposed)

### Entity registry
- `Entity`
  - `entity_id` (unique)
  - `domain`
  - `name`
  - `device_class` (optional)
  - `last_state` (string)
  - `last_changed` (datetime)
  - `last_seen` (datetime)
  - `attributes` (JSON)
  - `source`/`integration` (if multiple HA instances become supported)

### Rules
- `Rule`
  - `name`
  - `kind` (enum)
  - `enabled`
  - `priority` (int; higher first)
  - `definition` (JSON; includes `schema_version`)
  - `cooldown_seconds` (optional)
  - `created_by` (user)
  - timestamps

### Rule references (performance + reactivity)
- `RuleEntityRef`
  - `rule` FK
  - `entity` FK
  - derived from AST (so “entity X changed” only evaluates relevant rules)

### Temporal state for `FOR` and debouncing
- `RuleRuntimeState` (name flexible)
  - `rule` FK
  - `node_id` (string; identifies a subexpression in AST)
  - `became_true_at` / `last_true_at`
  - `scheduled_for` (datetime)
  - `active` (bool)

### Audit trail
- Extend/Reuse existing `AlarmEvent`:
  - `event_type = rule_fired`
  - metadata includes `rule_id`, `rule_kind`, actions, and (optional) a compact “explain trace” summary.

---

## Rule Definition Schema (JSON AST)
Keep it versioned and evolvable:

Top-level:
- `schema_version: 1`
- `when: ConditionNode`
- `then: ActionNode[]`
- `guards: GuardNode[]` (optional but recommended)
- `policy: { cooldown_seconds?, stop_after_fire?, ... }` (optional)

Condition nodes (examples, not final names):
- `{"op":"all","children":[...]}`
- `{"op":"any","children":[...]}`
- `{"op":"not","child":...}`
- `{"op":"entity_state","entity_id":"binary_sensor.front_door","equals":"on"}`
- `{"op":"numeric_compare","entity_id":"sensor.temp","path":"state","cmp":">","value":60}`
- `{"op":"for","seconds":300,"child":...}`
- `{"op":"alarm_state_in","states":["armed_away","armed_home"]}`
- `{"op":"time_window","tz":"local","start":"22:00","end":"06:00","days":[1,2,3,4,5]}`

Actions:
- `{"type":"alarm_disarm"}`
- `{"type":"alarm_arm","mode":"armed_night"}`
- `{"type":"alarm_trigger"}`
- `{"type":"ha_call_service","domain":"notify","service":"mobile_app","target":{"entity_ids":["notify.phone"]},"service_data":{"message":"Alarm triggered"}}`

---

## Evaluation Semantics (Determinism + Timing)

### Event-driven evaluation
- Evaluate candidate rules when:
  - an Entity changes state/attributes,
  - alarm state changes,
  - a scheduled timer fires (for `FOR` nodes).

### `FOR duration` semantics
- A `FOR` node becomes satisfied only if its child condition remains true continuously for the whole duration.
- Implementation note (for later coding): store per-rule/per-node runtime state and schedule a check at `t + duration`; cancel if child becomes false.

### Priority and conflicts
- Rules sorted by `priority desc`.
- Suggested v1 conflict policy:
  - `DISARM`: first-match-wins; stop after executing a disarm action successfully.
  - `TRIGGER`: first-match-wins (or stop-after-fire configurable).
  - `ESCALATE`: allow multiple but rate-limited.
  - `SUPPRESS`: evaluated before trigger rules (or higher default priority).

---

## UI/UX: Rules Page

### Primary screens
- Rules list: filter by kind, enabled, last fired, search by referenced entity.
- Rule editor:
  - `Kind`, `Name`, `Enabled`, `Priority`
  - `WHEN` builder: tree editor (groups + conditions + NOT)
  - Temporal decorators (`FOR`, debounce)
  - `GUARDS` (alarm state filters, schedule windows, cooldown)
  - `THEN` actions list: alarm actions + HA call_service
- Explain/Simulate:
  - pick entities and set mock states
  - run evaluation and show trace (which nodes true/false)
  - show which actions would run and why

### Removing Zones: replacement affordances
If grouping is still needed in UI, prefer one of:
- Tags/labels on entities (e.g. `entry`, `perimeter`, `interior`)
- Saved filters (“views”) for rule-building selection
- Device class–based suggestions (door/window/etc.) as helper defaults

---

## Migration Plan (from Zones/Sensors → Entities/Rules)
Goal: keep existing behavior working while moving configuration to rules.

1) Introduce Entity Registry and import/sync flow.
2) Introduce Rules with a minimal engine that can:
   - trigger/disarm/arm
   - run `FOR duration`
   - call HA services
3) Generate default rules from existing config (one-time migration):
   - For each existing “sensor trigger” mapping, create a trigger rule scoped to the old active states.
   - Convert “entry point” behavior into rule guards/actions (pending vs immediate trigger).
4) Remove Zones concept from UI:
   - replace zone UI with tags/filters or rule grouping
5) Deprecate and eventually remove Zone/Sensor models after data migration stabilizes.

---

## Testing/Validation (for later implementation)
- Unit: rule evaluation truth tables (AND/OR/NOT nesting).
- Unit: temporal behavior (`FOR`, debounce, cooldown).
- Integration: entity change → candidate rules evaluated → correct alarm transitions.
- Integration: HA call_service actions generate correct payloads and are rate-limited.
- Audit: rule-fired events logged with rule_id and action summary.

---

## Open Decisions (explicit)
- **Disarm from TRIGGERED**: Allowed (as requested). Default guardrails still recommended (cooldown + auditing).
- **Zones**: Removed. Grouping replaced by tags/filters and rule composition.
