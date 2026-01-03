# Onboarding Process Planning (Wizard + System Bootstrap)

## Goal
Design a first-run onboarding process that gets the system from “fresh install” to a *usable Home page* where a resident can safely arm/disarm and see meaningful device status.

This planning doc expands on the existing minimal onboarding endpoint described in `docs/ONBOARDING.md`.

## Why
Right now the system can create an admin + default settings profile, but:
- Arming/disarming is expected to use alarm PIN codes (and the UI assumes that).
- Zones/sensors (and later locks) must be configured to make “status” meaningful.
- Home Assistant integration will likely be the source of truth for device state.

The onboarding flow should prevent a “half-configured” system that looks broken.

## Scope

### In (Phase 1)
- Create first admin + alarm system record (already implemented).
- Ensure at least one usable alarm code exists (admin creates a PIN).
- Minimal HA connection configuration (URL + token) OR explicit “skip for now”.
- Minimal zone/sensor setup (manual add or import by HA entity IDs).
- A clear “setup required” experience after onboarding if any required pieces are missing.

### Out (later)
- Full automation builder
- Complex scheduling rules for temporary codes
- Notifications setup (SMS/push/email)
- Advanced HA discovery UX (entity browsing, filtering, grouping)
- Multi-home / multi-panel management

## Key Principle: Progressive Setup with Clear Gates
There are *two* phases:
1) **Bootstrap** (first admin/system/settings) – happens only when no users/system exist.
2) **Setup** (codes + HA + sensors) – can be completed over time, but Home should guide users until minimum requirements are met.

## Minimum Requirements for “Home Works”
Define the minimum “operational” state:
- **At least one active PIN code** for the current user (and/or a designated master/admin code).
- **Alarm settings profile is active** (already).
- **Alarm snapshot exists** (already).
- **At least one sensor** (optional for a minimal arm/disarm demo, but required for meaningful security).

Recommended gating:
- If `code_arm_required` is `true` and **no active codes exist**, require creating a code before enabling arm/disarm actions.
- Disarm should *always* require a valid code (already enforced in backend).
- Arming should warn (not hard-block) when sensors are unknown/down/unconfigured.

## Onboarding Stages

### Stage 0: First Boot (already)
Backend:
- `POST /api/onboarding/` creates:
  - Admin user + role assignment
  - AlarmSystem
  - Default active AlarmSettingsProfile
  - AlarmStateSnapshot (bootstrapped)

Frontend:
- `frontend/src/pages/OnboardingPage.tsx` handles the form and routes to login.

### Stage 1: Set Alarm Code(s) (new, should be early)
Goal: create at least one code so arm/disarm flows work.

UX:
- Immediately after first login (or as step 2 in onboarding wizard), present a “Create your alarm code” screen.
- Require: 4–8 digits.
- Optional: label (“Admin”, “Front keypad”).

Backend:
- Add endpoints to manage `accounts.UserCode` (MVP: create/list for current user).
  - `GET /api/codes/me/` (or `GET /api/codes/?mine=true`)
  - `POST /api/codes/` with `{ code, pin_length, label, code_type }`
- Use Django password hashing (`make_password/check_password`) for `code_hash`.

Policy:
- If no codes exist: show a blocking “Setup required: create a code” screen.
- Cancel-arming may remain code-free (explicit choice).
- No “master code” concept; codes are per-user.

### Stage 2: Connect Home Assistant (optional but recommended)
Goal: allow the system to read device state (sensors/locks) and later to trigger actions.

Inputs:
- Home Assistant base URL (local IP or hostname)
- Long-lived access token

Backend:
- Store HA connection details (encrypted at rest) in an integration model (new).
- Provide a “test connection” endpoint.

UX:
- Wizard step with “Test Connection” and “Skip for now”.
- If skipped: Home page shows “HA not connected” warning and disables HA-dependent features.

### Stage 3: Configure Zones + Sensors (new)
Goal: attach sensors to zones and map them to HA entities.

Approaches:
- **Manual add**: user enters zone name and sensor name + `entity_id`.
- **Import** (later): fetch entity registry from HA and let user pick.

Backend:
- Use existing `alarm.Zone` and `alarm.Sensor` models.
- Add API endpoints:
  - `GET/POST /api/alarm/zones/`
  - `GET/POST /api/alarm/sensors/`
- Add server-side validation that `entity_id` is unique per sensor (recommended).

Notes:
- Sensor “open/closed” state is currently not persisted; Phase 1 can show “unknown” until HA state ingestion is implemented.

### Stage 4: Locks (future-friendly)
Goal: optionally map locks to actions (e.g., unlock on disarm, lock on arm).

Data needs (future):
- `Lock` model with HA `entity_id`
- policy rules (what actions are allowed, what states)
- safety prompts (“Are you sure you want to auto-unlock on disarm?”)

For Phase 1:
- Only capture lock entities as “devices” with no automation.

### Stage 5: Review + System Check
Goal: ensure the user leaves onboarding confident.

Checklist:
- Code exists
- Alarm can arm/disarm (test action)
- Zones/sensors configured (or intentionally skipped)
- HA connected (or intentionally skipped)

## Backend “Setup Status” Contract
Add a single endpoint that drives UI gating:

`GET /api/onboarding/status/`
```json
{
  "onboarding_required": false,
  "setup_required": true,
  "requirements": {
    "has_active_settings_profile": true,
    "has_alarm_snapshot": true,
    "has_alarm_code": false,
    "has_zones": false,
    "has_sensors": false,
    "home_assistant_connected": false
  }
}
```

Frontend can use this to:
- Redirect to Setup Wizard when required.
- Show targeted banners on Home (“Create a code”, “Connect HA”, “Add sensors”).
- Disable only the features that can’t work yet (instead of blocking everything).

## UX Decisions to Make (MVP)
- Should we require at least one code *before showing Home*, or allow Home but with disabled arm/disarm actions?
- If `code_arm_required` is true but no codes exist, do we:
  - force a “Create Code” step, or
  - temporarily set `code_arm_required=false` until a code is created?
- Should we create a default admin code during onboarding? (Recommendation: no; user must choose it.)

## Acceptance Criteria (Phase 1)
- A fresh install can be fully configured to arm/disarm without confusing dead ends.
- If codes are missing, the UI guides the user to create one before they try to arm/disarm.
- HA connection can be skipped, but the UI makes it obvious what’s limited.
- Zones/sensors can be added (even manually) and appear on the Home page summary.

## Next Implementation Tasks (suggested order)
1) Add `GET /api/onboarding/status/` and use it in the frontend to gate “Setup required”.
2) Add minimal “create/list my codes” API + UI step to create the first PIN.
3) Add (or finish) zones/sensors CRUD and wire Home page zone summary to real backend data.
4) Add HA integration storage + test endpoint; later implement HA polling/subscription to update sensor state.
