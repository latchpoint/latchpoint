# ADR 0075: Move Integration Credentials to Environment Variables and Remove Encryption

## Status
**Superseded by [ADR 0079](0079-ui-config-with-encrypted-credentials.md)**

## Context

Integration credentials (tokens, passwords, API keys, URLs) are currently stored **encrypted in the database** inside `AlarmSettingsEntry.value` and `NotificationProvider.config` JSON blobs, using Fernet symmetric encryption with a `SETTINGS_ENCRYPTION_KEY` env var. Each credential field is prefixed with `enc:` on write and decrypted at runtime.

This approach was adopted in [ADR 0017](0017-home-assistant-connection-settings-in-profile.md) and centralized in [ADR 0038](0038-centralized-encryption-logic.md). While it works, it introduces significant complexity:

### Problems

1. **Encryption infrastructure overhead**: `alarm/crypto.py` provides `encrypt_secret`, `decrypt_secret`, `encrypt_config`, `decrypt_config`, `mask_config`, `prepare_runtime_config` -- six functions plus a migration management command (`encrypt_plaintext_secrets`), all to solve a problem that environment variables solve natively.

2. **Masking ceremony on every read**: Every API response must pass through `mask_config()` to replace secrets with `has_<field>` booleans. Every write must call `encrypt_secret()` and check `can_encrypt()`. This logic is repeated across views and serializers for Home Assistant, MQTT, Z-Wave JS, and all notification providers.

3. **Frontend credential management forms**: The UI has password-input components with "A token is already saved. Leave blank to keep it" / "Clear token" UX patterns for each integration. These forms add complexity for something the operator configures once during deployment.

4. **`SETTINGS_ENCRYPTION_KEY` is already an env var**: The encryption key itself lives in the environment, so we're using one env var to protect other values that could just as easily be env vars themselves. If an attacker has database access, they likely have environment access too (or vice versa). The encryption provides a false sense of additional security for a self-hosted appliance.

5. **Single-instance deployment**: Latchpoint is a self-hosted alarm system. There is one Home Assistant, one MQTT broker, one Z-Wave JS server. These are infrastructure-level connection parameters that belong in deployment configuration, not in a multi-profile database.

6. **Notification providers have limited multi-instance need**: While the `NotificationProvider` model supports multiple instances per type, in practice operators configure one Pushbullet account, one Discord webhook, etc. Environment variables handle this cleanly.

### Current Credential Inventory

| Integration | Setting Key | Encrypted Fields | Storage |
|------------|-------------|-----------------|---------|
| Home Assistant | `home_assistant_connection` | `token` | `AlarmSettingsEntry` |
| MQTT | `mqtt_connection` | `password` | `AlarmSettingsEntry` |
| Z-Wave JS | `zwavejs_connection` | `api_token` | `AlarmSettingsEntry` |
| Zigbee2MQTT | `zigbee2mqtt` | _(none)_ | `AlarmSettingsEntry` |
| Frigate | `frigate` | _(none)_ | `AlarmSettingsEntry` |
| Pushbullet | per-provider | `access_token` | `NotificationProvider` |
| Discord | per-provider | `webhook_url` | `NotificationProvider` |
| Slack | per-provider | `bot_token` | `NotificationProvider` |
| Webhook | per-provider | `auth_value` | `NotificationProvider` |
| HA Notify | per-provider | _(none, uses HA creds)_ | `NotificationProvider` |

### Current Enabled Mechanism

Each integration already has an `enabled` boolean inside its JSON config blob. Notification providers have `NotificationProvider.is_enabled`. These are managed through the UI and stored in the database. This ADR moves them to env vars as well, making them deployment-level decisions.

---

## Decision

Move all integration credentials and connection parameters to environment variables. Add an `<INTEGRATION>_ENABLED` env var for each integration and notification provider. Remove the encryption layer, credential UI forms, and associated backend masking/encrypt/decrypt logic.

### 1. New Environment Variables

#### Core Integrations

```bash
# Home Assistant
HA_ENABLED=false
HA_BASE_URL=http://localhost:8123
HA_TOKEN=
HA_CONNECT_TIMEOUT=2

# MQTT
MQTT_ENABLED=false
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_USE_TLS=false
MQTT_CLIENT_ID=latchpoint-alarm

# Z-Wave JS
ZWAVEJS_ENABLED=false
ZWAVEJS_WS_URL=ws://localhost:3000
ZWAVEJS_API_TOKEN=
ZWAVEJS_CONNECT_TIMEOUT=5

# Zigbee2MQTT (no secrets -- just enable + topic)
ZIGBEE2MQTT_ENABLED=false
ZIGBEE2MQTT_BASE_TOPIC=zigbee2mqtt

# Frigate (no secrets -- just enable + topic)
FRIGATE_ENABLED=false
FRIGATE_EVENTS_TOPIC=frigate/events
FRIGATE_RETENTION_SECONDS=3600
```

#### Notification Providers

```bash
# Pushbullet
PUSHBULLET_ENABLED=false
PUSHBULLET_ACCESS_TOKEN=
PUSHBULLET_TARGET_TYPE=all
PUSHBULLET_DEVICE_IDEN=
PUSHBULLET_EMAIL=
PUSHBULLET_CHANNEL_TAG=

# Discord
DISCORD_ENABLED=false
DISCORD_WEBHOOK_URL=
DISCORD_USERNAME=
DISCORD_AVATAR_URL=

# Slack
SLACK_ENABLED=false
SLACK_BOT_TOKEN=
SLACK_DEFAULT_CHANNEL=
SLACK_DEFAULT_USERNAME=
SLACK_DEFAULT_ICON_EMOJI=

# Webhook (generic)
WEBHOOK_ENABLED=false
WEBHOOK_URL=
WEBHOOK_METHOD=POST
WEBHOOK_CONTENT_TYPE=application/json
WEBHOOK_AUTH_TYPE=none
WEBHOOK_AUTH_VALUE=
WEBHOOK_MESSAGE_FIELD=message
WEBHOOK_TITLE_FIELD=title

# Home Assistant Notify (uses HA connection above)
HA_NOTIFY_ENABLED=false
HA_NOTIFY_SERVICE=notify.notify
```

### 2. Backend Config Modules: Read from Environment

Each integration's `config.py` will read directly from env vars instead of from `AlarmSettingsEntry`:

```python
# backend/integrations_home_assistant/config.py (after)
import environ

env = environ.Env()

def get_home_assistant_config() -> dict:
    return {
        "enabled": env.bool("HA_ENABLED", default=False),
        "base_url": env.str("HA_BASE_URL", default="http://localhost:8123"),
        "token": env.str("HA_TOKEN", default=""),
        "connect_timeout_seconds": env.float("HA_CONNECT_TIMEOUT", default=2),
    }
```

No encryption, no decryption, no masking. The config is read-only from the application's perspective.

### 3. Notification Providers: Env-Based Registry

Replace the `NotificationProvider` database model with an env-based provider registry. Each handler reads its own config from env vars:

```python
# backend/notifications/handlers/pushbullet.py (after)
class PushbulletHandler(NotificationHandler):
    provider_type = "pushbullet"
    display_name = "Pushbullet"

    @classmethod
    def from_env(cls) -> dict:
        return {
            "enabled": env.bool("PUSHBULLET_ENABLED", default=False),
            "access_token": env.str("PUSHBULLET_ACCESS_TOKEN", default=""),
            "target_type": env.str("PUSHBULLET_TARGET_TYPE", default="all"),
            # ...
        }
```

The `NotificationProvider` model stays for tracking delivery state (outbox, retries) but its `config` JSON field no longer stores secrets -- it references the env-based config at runtime.

### 4. Remove Encryption Infrastructure

Delete or gut the following:

| File | Action |
|------|--------|
| `alarm/crypto.py` | Remove `encrypt_secret`, `decrypt_secret`, `encrypt_config`, `decrypt_config`, `mask_config`, `prepare_runtime_config`, `can_encrypt`, Fernet key loading. Keep file if any non-encryption utils remain, otherwise delete. |
| `alarm/management/commands/encrypt_plaintext_secrets.py` | Delete entirely |
| `alarm/integration_settings_masking.py` | Delete (masking registry no longer needed) |
| `notifications/encryption.py` | Delete (re-export shim) |
| `alarm/tests/test_crypto_config_helpers.py` | Delete |
| Each integration `config.py` | Remove `*_ENCRYPTED_FIELDS`, `mask_*`, `prepare_runtime_*` functions. Replace with simple `get_*_config()` reading from env. |
| Each integration `views.py` | Remove encrypt-on-write and can_encrypt checks. Settings endpoints become read-only (return current env-based config, minus secrets) or are removed entirely. |
| Each integration `apps.py` | Remove `register_setting_masker()` calls |
| `notifications/serializers.py` | Remove encrypt/mask logic from `create()` and `update()` |

### 5. Remove Frontend Credential Forms

Remove the credential input/edit portions of each integration settings tab:

| Component | Action |
|-----------|--------|
| `HomeAssistantConnectionCard.tsx` | Remove token input, "Clear token" button, `tokenTouched` logic |
| `MqttSettingsForm.tsx` | Remove password input, "Clear password" button |
| `SettingsZwavejsTab.tsx` | Remove API token input |
| `AddEditProviderDialog.tsx` | Remove entirely (providers are configured via env, not UI) |
| `SettingsNotificationsTab.tsx` | Remove "Add provider" / "Edit provider" functionality. Show read-only list of enabled providers. |
| Settings model hooks | Simplify to read-only fetches (no save mutations for credential fields) |

The settings UI for each integration becomes a **read-only status view** showing:
- Whether the integration is enabled (from env)
- Connection parameters (URL, host, port -- no secrets)
- Current connection status

### 6. Settings API Endpoints

Integration settings endpoints change from read-write to **read-only** for connection config:

| Endpoint | Before | After |
|----------|--------|-------|
| `GET .../home-assistant/settings/` | Masked config from DB | Config from env (secrets omitted) |
| `PATCH .../home-assistant/settings/` | Update + encrypt to DB | **Remove** |
| `GET .../mqtt/settings/` | Masked config from DB | Config from env (secrets omitted) |
| `PATCH .../mqtt/settings/` | Update + encrypt to DB | **Remove** |
| `GET .../zwavejs/settings/` | Masked config from DB | Config from env (secrets omitted) |
| `PATCH .../zwavejs/settings/` | Update + encrypt to DB | **Remove** |

Zigbee2MQTT and Frigate settings that are non-credential (allowlists, denylists, known cameras, etc.) can remain DB-backed and UI-editable if desired, or also move to env vars. The `enabled` flag moves to env for all.

### 7. `AlarmSettingsEntry` Cleanup

Remove the following setting keys from `AlarmSettingsEntry` rows and the settings registry:

- `home_assistant_connection` (entirely env-backed now)
- `mqtt_connection` (entirely env-backed now)
- `zwavejs_connection` (entirely env-backed now)

A data migration should clean up these rows. The `AlarmSettingsEntry` model itself remains for non-credential settings (rules, entity configuration, etc.).

For Zigbee2MQTT and Frigate, their non-credential settings (`allowlist`, `denylist`, `known_cameras`, `known_zones_by_camera`, etc.) can stay in `AlarmSettingsEntry` -- only the `enabled` flag moves to an env var.

### 8. `SETTINGS_ENCRYPTION_KEY` Removal

Once all encrypted values are removed from the database:

1. Remove `SETTINGS_ENCRYPTION_KEY` from `.env.example`
2. Remove the Fernet key loading from `crypto.py`
3. Remove the `cryptography` package dependency (if unused elsewhere)
4. Add `SETTINGS_ENCRYPTION_KEY` to a deprecation notice in release notes

### 9. Cascading Disable Logic

The existing cascading disable logic (MQTT disabled -> Zigbee2MQTT and Frigate auto-disabled) becomes simpler with env vars: the startup validation checks that dependent integrations' env vars are consistent. For example, if `ZIGBEE2MQTT_ENABLED=true` but `MQTT_ENABLED=false`, log a warning and treat Zigbee2MQTT as disabled.

---

## Migration Path

### Phase 1: Add Env Var Reading (Backward Compatible)

- Add `get_*_config()` functions that read from env vars
- Each function falls back to the DB-stored value if the env var is not set (migration period)
- Add `*_ENABLED` env var support alongside the existing `enabled` JSON field
- Update `.env.example` with all new variables

### Phase 2: Update Runtime Consumers

- Point all runtime consumers (gateways, connection managers, notification dispatch) at the new `get_*_config()` functions instead of `prepare_runtime_*` decryption functions
- Integration `apps.py` startup hooks read from env instead of DB

### Phase 3: Remove Write Paths

- Remove `PATCH` endpoints for integration credentials
- Remove frontend credential input forms
- Remove `AddEditProviderDialog` and provider CRUD for notification secrets
- Settings UI becomes read-only status display

### Phase 4: Remove Encryption Infrastructure

- Delete `encrypt_secret`, `decrypt_secret`, `encrypt_config`, `decrypt_config`, `mask_config`, `prepare_runtime_config`
- Delete `encrypt_plaintext_secrets` management command
- Delete `integration_settings_masking.py` registry
- Delete `notifications/encryption.py`
- Remove `SETTINGS_ENCRYPTION_KEY` from `.env.example`
- Remove `cryptography` dependency (if unused elsewhere)
- Add Django migration to clean up old `AlarmSettingsEntry` rows for credential settings

### Phase 5: Supersede ADRs

- Mark [ADR 0017](0017-home-assistant-connection-settings-in-profile.md) as **Superseded by 0075**
- Mark [ADR 0038](0038-centralized-encryption-logic.md) as **Superseded by 0075**

---

## Alternatives Considered

### 1. Keep Encrypted DB Storage, Simplify the Code
**Rejected**: The encryption adds complexity without meaningful security benefit for a self-hosted appliance. The `SETTINGS_ENCRYPTION_KEY` is already an env var -- we're using an env var to protect values that should just be env vars.

### 2. Use Django's Built-In Secret Storage or django-encrypted-model-fields
**Rejected**: Still stores secrets in the DB. Same fundamental issue -- the encryption key is in the environment anyway.

### 3. External Secret Manager (Vault, AWS Secrets Manager)
**Rejected**: Overkill for a self-hosted alarm panel. Adds operational complexity and external dependencies.

### 4. Keep Notification Providers in DB, Only Move Integration Creds to Env
**Considered**: Notification providers already have a clean model with `is_enabled`. However, the user explicitly wants all credentials out of the DB, and the notification providers are the primary users of the encryption pipeline. Leaving them in the DB means we can't remove the encryption code.

### 5. Support Multiple Notification Provider Instances via Indexed Env Vars
**Deferred**: If multiple instances of the same provider type are needed in the future (e.g., two Discord webhooks), we could support `DISCORD_1_WEBHOOK_URL`, `DISCORD_2_WEBHOOK_URL` etc. For now, one instance per type is sufficient.

---

## Consequences

### Positive
- **Eliminates encryption complexity**: ~200 lines of crypto code, masking registry, migration command, and per-integration encrypt/decrypt wrappers all go away
- **Simpler deployment**: Operators configure everything in one place (`.env` or Docker Compose env section) rather than splitting between env vars and UI
- **No `SETTINGS_ENCRYPTION_KEY` requirement**: One fewer secret to manage
- **Faster startup**: No Fernet key initialization or DB queries for connection config
- **Simpler frontend**: Settings pages become read-only status displays instead of complex forms with token-touched tracking and mask/clear logic
- **Better Docker/K8s alignment**: Secrets as env vars is the standard pattern for containerized services

### Negative
- **No UI-based credential editing**: Operators must redeploy (or restart with new env vars) to change credentials. This is acceptable for a self-hosted appliance where credential changes are rare.
- **Migration effort**: Existing deployments need to move credentials from the DB/UI to env vars during upgrade
- **Single instance per notification type**: Can't have two separate Pushbullet accounts. Mitigated by the deferred indexed env var approach if needed.
- **Supersedes two previous ADRs**: ADR 0017 and ADR 0038 decisions are reversed

### Neutral
- `AlarmSettingsEntry` model remains for non-credential settings
- `NotificationProvider` model may remain for delivery tracking (outbox/retries) but loses its `config` role for secrets
- TOTP secrets in `UserTOTPDevice.secret_encrypted` are **not affected** (user auth secrets have different threat model)
- User alarm PIN hashes in `UserCode.code_hash` are **not affected** (these are hashed, not encrypted)

---

## Todos

- Add env var reading functions (`get_*_config()`) for each integration
- Add `*_ENABLED` env vars for all integrations and notification providers
- Update `.env.example` with complete variable list and documentation
- Update `docker-compose.yml` / deployment docs with new env vars
- Migrate runtime consumers to use env-based config
- Remove `PATCH` endpoints for credential settings
- Remove frontend credential input forms and make settings read-only
- Delete encryption infrastructure (crypto functions, masking registry, migration command)
- Write Django migration to clean up old `AlarmSettingsEntry` credential rows
- Remove `SETTINGS_ENCRYPTION_KEY` from `.env.example`
- Evaluate removing `cryptography` package dependency
- Mark ADR 0017 and ADR 0038 as superseded
- Update AGENTS.md if it references encryption patterns

## References

- [ADR 0017: Home Assistant Connection Settings in Profile (Encrypted)](0017-home-assistant-connection-settings-in-profile.md) -- **Superseded by this ADR**
- [ADR 0038: Centralized Encryption Logic](0038-centralized-encryption-logic.md) -- **Superseded by this ADR**
- [ADR 0044: Notifications Architecture (Consolidated)](0044-notifications-architecture-consolidation.md)
- Current encryption: `backend/alarm/crypto.py`
- Current masking registry: `backend/alarm/integration_settings_masking.py`
- Current notification encryption: `backend/notifications/encryption.py`
