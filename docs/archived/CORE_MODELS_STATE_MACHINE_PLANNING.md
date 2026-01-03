# Core Models and State Machine Planning

> Archived: implemented and/or superseded; kept for historical context.

## Goal
Define the minimal, durable data model and alarm state machine needed for Phase 1.

## Scope
- Core alarm settings, state, and events.
- User codes (permanent only for MVP).
- Zones/sensors minimal structure for state transitions.
- Timing rules (entry/exit/trigger).
- Audit-friendly event log.

Out of scope: notifications, automations, MQTT, HA entity mapping details.

## Core Models (MVP)

### User
- Custom user model in `backend/accounts`.
- Fields: email/username, display_name, role (admin, resident, guest, service).

### AlarmSettingsProfile
- name (string)
- is_active (bool)
- delay_time (int seconds)
- arming_time (int seconds)
- trigger_time (int seconds)
- disarm_after_trigger (bool)
- code_arm_required (bool)
- available_arming_states (array of enum)
- state_overrides (JSON, keyed by state, overrides for delay/arming/trigger)
- audio_visual_settings (JSON, minimal for MVP)
- sensor_behavior (JSON, warn_on_open_sensors, force_arm_enabled)
- notification_settings (JSON, minimal for Phase 1–2)
  - `home_assistant_notify`:
    - `enabled` (bool)
    - `service` (string, e.g. `notify.notify` or `notify.mobile_app_*`)
    - `events` (object of booleans by event key, e.g. `armed_away`, `disarmed`, `pending`, `triggered`)
    - `cooldown_seconds` (int, optional)
    - `templates` (optional: title/body per event with variables)

### AlarmStateSnapshot
- current_state (enum: disarmed, arming, armed_home, armed_away, armed_night, armed_vacation, pending, triggered)
- previous_state (enum or null)
- target_armed_state (enum or null, for arming/return after trigger)
- settings_profile (FK to AlarmSettingsProfile)
- entered_at (datetime)
- exit_at (datetime nullable, for timed transitions)
- last_transition_reason (string enum or freeform)
- last_transition_by (FK to User nullable, for system transitions)
- timing_snapshot (JSON, effective timing values captured at arm time)

### AlarmEvent
- event_type (enum: armed, disarmed, pending, triggered, code_used, sensor_triggered, failed_code, state_changed)
- state_from (enum nullable)
- state_to (enum nullable)
- timestamp (datetime)
- user (FK nullable)
- code_id (FK nullable)
- zone_id (FK nullable)
- sensor_id (FK nullable)
- metadata (JSON for details)

### AlarmCode (Permanent only for MVP)
- Reuse `accounts.UserCode` for MVP (permanent codes only).
- Extend permissions and lockout via ADR 0002.

### Zone (Minimal)
- name (string)
- is_active (bool)
- entry_delay_override (int nullable)
- active_states (array of enum)

### Sensor (Minimal)
- name (string)
- zone (FK)
- entity_id (string, optional for later HA mapping)
- is_active (bool)
- is_entry_point (bool)

## State Machine

### States
- disarmed
- arming (exit delay running)
- armed_home
- armed_away
- armed_night
- armed_vacation
- pending (entry delay running)
- triggered

### Commands (inputs)
- arm(target_state, user, code?)
- disarm(user, code)
- cancel_arming(user, code?)
- sensor_triggered(sensor, timestamp)
- timer_expired(timer_type)

### Transition Rules (high level)
- disarmed -> arming on arm command
- arming -> armed_* when arming_time expires
- arming -> disarmed on cancel_arming
- armed_* -> pending when entry sensor triggers
- pending -> disarmed on valid code
- pending -> triggered when delay_time expires
- triggered -> disarmed on valid code
- triggered -> armed_* or disarmed on trigger_time based on disarm_after_trigger

### Timing Resolution
- Resolve delay/arming/trigger using:
  1) state overrides from AlarmSettingsProfile
  2) zone entry delay override if sensor triggered and pending
  3) global defaults

### Invariants
- Only one active AlarmStateSnapshot at a time.
- Every state transition emits an AlarmEvent.
- Timed transitions must be idempotent (ignore if state changed).
- Code validation always required for disarm.
- Code required to arm only if code_arm_required is true.

## Persistence and Concurrency
- State transitions must be atomic (db transaction + select for update).
- Store next timer expiration in AlarmStateSnapshot.exit_at.
- Background task checks for expired timers and runs transitions.

## Open Questions
- See `docs/adr/0001-core-models-state-machine.md` for decisions, alternatives, and todos.

## Next Steps
- Validate model names/fields against existing conventions in `backend/`.
- Draft initial Django models and enums.
- Add basic API endpoints for arm/disarm and state read.
- Add unit tests for transition rules and timer resolution.

## MVP Plan (Core Models + State Machine)

### Phase 1A: Model + Enum Skeletons
- Define enums for alarm states, event types, and code types.
- Implement models: AlarmSettingsProfile, AlarmStateSnapshot, AlarmEvent, AlarmCode, Zone, Sensor.
- Add minimal model constraints and indexes (state, timestamps).

### Phase 1B: State Transition Service
- Implement atomic transition function with select-for-update on AlarmStateSnapshot.
- Apply ADR rules for entry vs non-entry sensors and previous/target state handling.
- Persist AlarmEvent on every transition.

### Phase 1C: Timing + Background Processing
- Add exit_at on snapshot; resolve timing using effective settings snapshot.
- Create task/management command to process expired timers.
- Ensure idempotency for timer-driven transitions.

### Phase 1D: API Surface
- Endpoints: read current state, arm, disarm, cancel arming.
- Include code validation + rate limit hooks (enforcement later if needed).

### Phase 1E: Tests
- Unit tests for transition rules, timing resolution, and permission checks.
- Concurrency test for simultaneous transitions (transaction safety).

## Known Issues / Gaps to Resolve
- Resolved decisions captured in `docs/adr/0001-core-models-state-machine.md`.
