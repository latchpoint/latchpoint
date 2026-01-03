# Setup Status & Required Settings Planning

> Archived: implemented; kept for historical context.

## Goal
Define the exact “setup requirements” that gate access to the logged-in app (Home page), and document the settings/configuration needed to make the system operational.

This doc is the concrete reference for:
- The backend `GET /api/onboarding/setup-status/` contract
- The frontend “hard redirect to /setup” behavior
- What “minimum viable configuration” means for Phase 1

## Definitions

### Onboarding vs Setup
- **Onboarding (first boot)**: Creating the first admin + AlarmSystem + default AlarmSettingsProfile + AlarmStateSnapshot.
- **Setup (post-login wizard)**: Completing required configuration to make the dashboard usable and security flows coherent.

### “Home Works” (Phase 1)
The user can:
- See current alarm state.
- Arm (if allowed by settings and a code exists).
- Disarm (always code-required).
- View zones/sensors list (even if sensor states are “unknown” initially).

## Required Settings / Requirements (Phase 1)

### 1) Alarm Settings Profile
**Requirement flag**: `has_active_settings_profile`

What it means:
- A single active `AlarmSettingsProfile` exists (`is_active=true`).

Why it matters:
- Drives the arming/disarming policy and timing.

Fields required for MVP Home flows:
- `delay_time`, `arming_time`, `trigger_time`
- `code_arm_required`
- `available_arming_states`
- `sensor_behavior.force_arm_enabled`

Bootstrap behavior (current):
- On first boot, a default active profile is created if missing.

### 2) Alarm State Snapshot
**Requirement flag**: `has_alarm_snapshot`

What it means:
- At least one `AlarmStateSnapshot` exists.

Why it matters:
- Home needs a canonical state source with timer context (`entered_at` / `exit_at`).

Bootstrap behavior (current):
- Snapshot is created during onboarding if missing.

### 3) Alarm Code (PIN)
**Requirement flag**: `has_alarm_code`

What it means:
- The current user has at least one active `accounts.UserCode` (`is_active=true`).

Why it matters:
- Disarm is always code-required.
- Arm may be code-required depending on `code_arm_required`.

Policy:
- Setup is considered incomplete if `has_alarm_code=false`.
- The app performs a hard redirect to `/setup` until a code exists.

Code constraints (Phase 1):
- 4–8 digits only.
- Stored as `code_hash` (Django password hashing); never returned to clients.
- `code_type` defaults to `permanent`.
- No “master code” concept; all codes belong to a user.

### 4) Zones
**Requirement flag**: `has_zones`

What it means:
- At least one `alarm.Zone` exists.

Why it matters:
- Allows the Home dashboard to communicate “coverage” and structure.

Phase 1 policy:
- Not required to pass setup gate, but recommended.
- If missing, Setup Wizard should show “Add zones” as a next step.

### 5) Sensors
**Requirement flag**: `has_sensors`

What it means:
- At least one `alarm.Sensor` exists.

Why it matters:
- Without sensors, arming is mostly a demo mode; security monitoring is not meaningful.

Phase 1 policy:
- Not required to pass setup gate (to keep initial setup simple).
- Setup Wizard should recommend adding at least one entry sensor.

### 6) Home Assistant Connection
**Requirement flag**: `home_assistant_connected`

What it means:
- Backend has valid HA connection settings and successfully passed a recent connectivity check.

Why it matters:
- Sensor state, locks, and automation rely on HA as a device/state provider.

Phase 1 policy:
- Optional (“Skip for now”), but strongly recommended.
- If disconnected, the UI should show an obvious warning and treat sensor states as unknown.

### 7) Home Assistant Push Notifications (optional)
What it means:
- The system is configured to send Home Assistant `notify.*` messages on selected alarm state changes (arm/disarm/pending/triggered).

Why it matters:
- Provides immediate “push” awareness without requiring a separate notification provider.

Phase 1 policy:
- Optional and not a setup gate.
- If HA is disconnected, this feature is effectively unavailable and should be shown as “Offline”.

## Backend Contract: Setup Status Endpoint

Endpoint:
- `GET /api/onboarding/setup-status/` (authenticated)

Response shape (canonical, camelCase over the wire due to API transformer):
```json
{
  "onboardingRequired": false,
  "setupRequired": true,
  "requirements": {
    "hasActiveSettingsProfile": true,
    "hasAlarmSnapshot": true,
    "hasAlarmCode": false,
    "hasZones": false,
    "hasSensors": false,
    "homeAssistantConnected": false
  }
}
```

Computation rules (Phase 1):
- `setupRequired = !(hasActiveSettingsProfile && hasAlarmSnapshot && hasAlarmCode)`
- `onboardingRequired` is `false` once initial onboarding is completed.

## Frontend Behavior: Setup Gate

### Hard Redirect Rule
If authenticated and `setupRequired=true`, redirect to `Routes.SETUP` (`/setup`).

### Exit Rule
If at `/setup` and `setupRequired=false`, redirect to `Routes.HOME` (`/`).

### UX in the wizard
Phase 1 wizard should:
1) Require creating a PIN code (blocking step).
2) Offer optional next steps (HA, zones, sensors) as “Continue later”.

## Future Settings (planned, not required yet)

### Locks
Likely settings needed:
- HA `entity_id` mapping for locks
- policy toggles: auto-lock on arm, auto-unlock on disarm (with confirmations)

### Sensor State Ingestion
Likely settings needed:
- polling interval or websocket subscription mode
- entity mapping rules
- “unknown state” handling and fallback behavior

### Notifications
Settings:
- channels enabled (push/email/sms)
- recipient routing
- event types to notify on

## Open Questions
- Should `has_sensors` become a hard requirement once HA integration is present?
- Should arming be blocked or warned when sensors are unknown/down/unconfigured? (Decision: warn, do not hard-block.)
