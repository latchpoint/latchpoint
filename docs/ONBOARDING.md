# Onboarding (First Boot)

The backend exposes a minimal, unauthenticated onboarding API to create the first admin and bootstrap core alarm data.

## Endpoint

`POST /api/onboarding/`

## Setup gating (after login)

The frontend redirects authenticated users to the setup wizard when minimum “Home works” requirements are not met (e.g., no alarm PIN exists yet).

`GET /api/onboarding/setup-status/` (authenticated)

### Response (200)

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

### Request

```json
{
  "email": "admin@example.com",
  "password": "StrongPass123!",
  "home_name": "Primary Residence"
}
```

`email` may also be sent as `username`.

### Response (201)

```json
{
  "user_id": "uuid",
  "email": "admin@example.com",
  "home_name": "Primary Residence",
  "timezone": "UTC"
}
```

## Behavior

- Allowed only when no users and no alarm system exist; otherwise returns `409`.
- Creates a superuser + assigns the `admin` role.
- Creates the alarm system record with `home_name` and `TIME_ZONE` from env.
- Ensures a default active alarm settings profile exists.
- Bootstraps the alarm state snapshot.

## Configuration

- `TIME_ZONE` in `.env` drives onboarding timezone defaults.
