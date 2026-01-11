# ADR 0065: Rule Builder WHEN Time Ranges

## Status
**Proposed**

## Context
The rules UI supports building `definition.when` conditions for alarm state, entity state, and Frigate detections (ADR 0033), but it cannot express a very common guardrail: “only run this rule during certain hours.”

Users want to build rules like:
- “If a door opens **at night (22:00–06:00)** then trigger the alarm.”
- “If motion is detected **during business hours (Mon–Fri 09:00–17:00)** then turn on lights.”

Today, this requires editing JSON manually or pushing this logic to Home Assistant automations, which undermines the goal of the alarm panel being the primary automation surface.

Constraints:
- Rules should remain portable and readable in the existing JSON DSL.
- Time handling must be unambiguous across time zones and DST.
- Dispatcher routing relies on entity dependencies (ADR 0057/0059); time conditions must not accidentally create “never fires” rules.

## Decision
Add a first-class time range condition operator to the rules DSL and expose it in the Rules UI builder as a new WHEN condition.

### DSL shape (schema_version=1)
Add a condition node:

```json
{
  "op": "time_in_range",
  "start": "22:00",
  "end": "06:00",
  "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
  "tz": "system"
}
```

Fields:
- `start` / `end`: required 24-hour local times in `HH:MM` format.
- `days`: optional list of day strings (`mon`..`sun`); default is all days.
- `tz`: optional time zone selector:
  - `"system"` (default): interpret the range in the backend/system time zone.
  - An IANA time zone ID (e.g. `"America/New_York"`) for explicit user selection.

Semantics:
- The range is inclusive of `start` and exclusive of `end` (to avoid “double hit” at boundaries when combined with scheduler ticks in the future).
- If `end` is earlier than `start`, the range wraps across midnight (e.g. `22:00–06:00`).
- `start == end` is invalid (ambiguous; “always” should be expressed by omitting the operator).

### Rules UI (React Query Builder)
Add a new WHEN field:
- Label: “Time of day”
- Operator: “is between”
- Value editor: two time inputs (`start`, `end`) + optional day-of-week picker + time zone selector (“System time zone” default).

The RQB ↔ DSL conversion layer (ADR 0033) is extended to map this field to/from `op: "time_in_range"`.

### Guardrails (to avoid non-firing rules)
Until the dispatcher supports time-based reevaluation ticks, the UI prevents “time-only” rules by requiring at least one entity/alarm/Frigate-dependent condition alongside `time_in_range`. In other words, `time_in_range` is initially a guard condition, not a standalone trigger.

## Alternatives Considered
- Use Home Assistant automations for schedule gating.
  - Rejected: splits rule logic across systems and reduces the value of the in-app rules UI.
- Add cron-like scheduled rules (“at 22:00 do X”) instead of a WHEN time range.
  - Deferred: this is a different feature (time trigger vs time guard); time ranges are still needed even with scheduled triggers.
- Interpret times in UTC only.
  - Rejected: confusing UX; users think in local time and DST matters.

## Consequences
- Adds a new non-entity condition operator, expanding the rules DSL contract (schema_version still 1).
- Requires consistent time zone/DST semantics across backend evaluation and frontend editing.
- Without time-based reevaluation support, time range conditions must be used as guards for entity-driven rules; pure schedule-based rules remain out of scope for this ADR.

## Todos
- Backend:
  - Implement `time_in_range` evaluation using a timezone-aware `now` and `zoneinfo` conversion.
  - Add definition validation errors that are field-specific (`start`, `end`, `days`, `tz`).
- Frontend:
  - Add “Time of day” field + value editor to the rules builder.
  - Extend RQB ↔ DSL conversion and add unit tests for round-trip transformations.
  - Enforce the UI guardrail preventing “time-only” rules (until time ticks exist).
- Docs:
  - Add a user-facing example rule for “night-only door open triggers alarm.”
