# ADR-0095: Deprecate profile-level timing settings; move exit-delay configuration into the `alarm_arm` action

## Status
Proposed

## Date
2026-05-19

## Context

ADR-0094 introduced composable rule-action primitives. The rules engine can now express entry-delay, exit-delay, trigger-duration, and cooldown behaviors directly via `alarm_set_state`, generic `delay_seconds` on any action, `op: for` on WHEN clauses, and rule-level `cooldown_seconds`.

Four profile-level timing settings predate the rules engine and remain in the `AlarmSettingsProfile`:

- `delay_time` — entry-delay duration for the legacy `Sensor.is_entry_point` flow
- `trigger_time` — TRIGGERED state auto-exit duration
- `state_overrides[<state>].arming_time` — exit-delay duration per armed state
- `disarm_after_trigger` — whether TRIGGERED auto-disarms (true) or returns to previous armed state (false) when `trigger_time` expires

These settings have three problems:

### Problem 1: `delay_time` is dormant config

`delay_time` is consumed only by `state_machine.transitions.sensor_triggered()` (transitions.py:132). `sensor_triggered()` is exported from `state_machine/__init__.py` but has no live callers in production code — no MQTT, Home Assistant, or Z-Wave event handler routes through it. The setting is editable in the UI and stored in the DB, but changing its value has zero observable effect. Operators reasonably expect changing "entry delay" to affect their alarm's PENDING duration; the actual entry delay lives in their rules (`op: for, seconds: N` on the WHEN clause, or `delay_seconds: N` on a queued `alarm_set_state(triggered)` action).

### Problem 2: duplicated configuration surface

`trigger_time` and `arming_time` ARE actively consumed, but the same behavior is expressible in rules. Once a behavior can be expressed in two places, operators cannot answer "where does my exit delay come from" without inspecting both surfaces. The rule-builder version is strictly more expressive (per-rule, conditional, composable); the profile version is a silent fallback.

### Problem 3: ARMING-state coupling through `arming_time = 0`

`arm()` (transitions.py:42-52) treats `arming_time <= 0` as "skip ARMING entirely; transition directly to armed." So changing `arming_time` from 60 to 0 doesn't just shorten the exit delay — it removes ARMING from the flow entirely, defeating the purpose of having ARMING as a distinct state for keypad indicators and `cancel_arming()`. That's a surprising coupling for a setting labeled "exit delay duration."

## Decision

Move all timing behavior into the rule builder; remove timing-shaped configuration from the profile.

1. **Remove** these `AlarmSettingsEntry` keys entirely: `delay_time`, `trigger_time`, `state_overrides`, `disarm_after_trigger`. Drop them from `settings_registry.py`, the API serializers, and the frontend settings UI (`AlarmTimingCard`, `AlarmBehaviorCard`).

2. **Add** a new optional field on the `alarm_arm` action handler: `arming_time_seconds` (non-negative int, max 600). When present and >0, `alarm_arm()` enters ARMING with `exit_at = now + arming_time_seconds`. When absent or 0, the alarm transitions directly to the armed state with no ARMING.

3. **Remove** the dormant `sensor_triggered()` state-machine function (`transitions.py:112-154`) and the `Sensor.is_entry_point` model field. They are bound to the deprecated `delay_time` flow and have no live callers in production code.

4. **Remove** the `TimingSnapshot` dataclass (`state_machine/timing.py`), the `AlarmStateSnapshot.timing_snapshot` JSON column, and the `base_timing` / `resolve_timing` / `timing_from_snapshot` helpers. With all three timing fields gone, they carry no information.

5. **Migrate** existing data:
   - For each `alarm_arm` action in `Rule.definition.then` across all rules, set `arming_time_seconds` from the active profile's `state_overrides[mode].arming_time` value (when >0).
   - For each profile with `disarm_after_trigger=true` AND `trigger_time>0`: create a corresponding `disarm`-kind rule that fires when alarm has been TRIGGERED for `trigger_time` seconds.
   - Delete the four `AlarmSettingsEntry` rows.
   - Drop `AlarmStateSnapshot.timing_snapshot` column.

6. **Trigger-duration behavior post-ADR**: operators who want TRIGGERED to auto-fall-back must express it as a rule:
   ```json
   {"kind": "disarm",
    "when": {"op": "for", "seconds": 60,
             "child": {"op": "alarm_state_in", "states": ["triggered"]}},
    "then": [{"type": "alarm_disarm"}]}
   ```
   For users who had `disarm_after_trigger: false` with `trigger_time: 0` (TRIGGERED stays until manually cleared), no rule is needed — that's the default behavior post-ADR.

## Consequences

### Positive
- Single source of truth for timing: rules.
- Profile becomes coherent — environment + system policy, no behavior knobs.
- Per-rule timing overrides are trivial; each `alarm_arm` action carries its own exit delay.
- Removes ~150 LoC of dead/dormant code (`sensor_triggered`, `is_entry_point`, `TimingSnapshot`, related helpers, dead UI components).
- Eliminates the surprising ARMING-state coupling.

### Negative
- No profile-level default — if you have 5 arm-rules wanting 60s exit delay, you set 60s in 5 places. Acceptable trade-off given operators rarely have multiple arm-rules per state.
- Migration touches every rule with an `alarm_arm` action. Down-migration restores profile entries from action parameters.
- `disarm_after_trigger=true` users get a generated `disarm`-kind rule; their behavior is preserved but their config moves.

### Neutral
- ARMING state remains a distinct state with `target_armed_state` and `cancel_arming()`. Only the *duration* moves into the rule action; state-machine semantics are unchanged.
- No new primitives; pure deletion + one new parameter on an existing handler.

## Alternatives considered

**(B) Compose ARMING via `alarm_set_state(arming)`** — relax ADR-0094's rejection so operators write the multi-step flow explicitly. Rejected: exposes `target_armed_state` plumbing and contradicts ADR-0094 directly.

**(C) Kill the ARMING state entirely** — make `alarm_arm` a "wait N seconds and transition" action with no intermediate state. Rejected: loses the keypad arming-indicator semantics and the `cancel_arming()` distinct operation.

**(D) Cascade — profile defaults + per-rule overrides** — adds more configuration surface, not less, with precedence rules. Rejected: the goal is one surface, not two with ordering.

## References

- ADR-0079: All config DB-backed (settings registry pattern)
- ADR-0091: Rule-action entry delay (superseded by ADR-0094)
- ADR-0094: Composable rule-action primitives (foundation this ADR builds on)
