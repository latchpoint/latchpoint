# ADR 0017: Home Assistant Connection Settings in Alarm Profile (Encrypted)

## Status
**Implemented**

## Context
Home Assistant connectivity used to be configured via environment variables.
That approach has drawbacks:
- Not editable from the UI (requires redeploy/restart and secret management outside the app).
- Harder to support multiple alarm profiles/environments consistently.
- Creates drift between “settings in the UI” vs “settings in deployment”.

Home Assistant access tokens are secrets and must be stored encrypted at rest.

## Decision
We will store Home Assistant connection settings in the active alarm settings profile and make them editable via the UI.

### Storage
- Add a new alarm profile setting key: `home_assistant_connection` (JSON).
- Shape (normalized):
  - `enabled: bool`
  - `base_url: str` (e.g., `http://homeassistant.local:8123`)
  - `token: str` (stored encrypted using `alarm.crypto.encrypt_secret`, prefixed with `enc:`)
  - optional: `connect_timeout_seconds: int` (defaults to existing HA status call timeouts)

### Encryption / masking rules
- Persisted `token` is always encrypted at rest.
  - API writes MUST reject saving a non-empty token when `SETTINGS_ENCRYPTION_KEY` is not configured.
- API reads MUST NOT return the raw token.
  - Return `has_token: bool` (or equivalent) instead.

### API surface
Owned by the Home Assistant integration Django app:
- `GET /api/alarm/home-assistant/settings/` → normalized + masked connection settings
- `PATCH /api/alarm/home-assistant/settings/` → partial update (supports “keep existing token if not provided” semantics)

Existing HA endpoints use the profile-backed connection:
- `GET /api/alarm/home-assistant/status/`
- `GET /api/alarm/home-assistant/entities/`
- `GET /api/alarm/home-assistant/notify-services/`

### Runtime wiring
All HA calls route through a gateway that reads the active profile’s `home_assistant_connection` and uses the decrypted token at runtime.
Environment variables are not used for configuring Home Assistant connectivity.

## Alternatives Considered
- Keep env-based configuration.
  - Pros: simple, external secret management.
  - Cons: not UI-editable; harder UX; not profile-aware.

- Store token plaintext in DB (rejected).
  - Pros: simplest implementation.
  - Cons: unacceptable security risk.

- Store token in DB but without enforcing `SETTINGS_ENCRYPTION_KEY`.
  - Pros: fewer deployment prerequisites.
  - Cons: easy to end up with plaintext secrets; undermines “encrypted at rest” requirement.

## Consequences
- Better UX: HA connection can be configured and updated from the UI.
- Security: requires `SETTINGS_ENCRYPTION_KEY` for token persistence; must be documented in deployment.
- Requires small refactor so HA API/gateway reads from the profile instead of Django settings.

## Todos
- Add `home_assistant_connection` to the settings registry via per-app registration (preferred) or as a transitional key in the central registry.
- Implement serializers + views for `.../home-assistant/settings/` with masking and encryption enforcement.
- Update HA gateway implementation to read profile-backed settings and decrypt token at runtime.
- Decide on and implement env→profile migration behavior (command or startup hook) and document deprecation.
