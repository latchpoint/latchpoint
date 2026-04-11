# ADR 0079: Move All Integration Config to UI with Encrypted Credentials

## Status
**Proposed**

## Context

ADR 0075 moved all integration credentials and connection parameters to environment variables and removed the encryption infrastructure entirely. ADR 0078 partially reversed this by moving `enabled` flags back to the DB for UI toggling. However, connection config (URLs, tokens, passwords, API keys) still lives in env vars and is read-only in the UI.

This creates real friction for a self-hosted alarm system:

### Problems with env-var-based connection config

1. **Setup requires file editing**: New users must manually edit `.env` or `docker-compose.yml` to configure any integration. There is no setup wizard or UI-driven onboarding. For a self-hosted appliance targeting home users, this is a significant barrier.

2. **Credential changes require restart**: Rotating a Home Assistant long-lived access token, updating an MQTT password, or changing a Discord webhook URL all require editing env files and restarting the container.

3. **No multi-profile credential isolation**: `AlarmSettingsProfile` supports multiple switchable configurations, but connection credentials are global env vars. A "testing" profile and a "production" profile share the same HA token and MQTT broker — there is no way to have profile-specific connection config.

4. **Notification provider rigidity**: The env-var pattern supports exactly one instance per provider type. You cannot have two Discord webhooks (e.g., one for critical alerts, one for informational) or two Pushbullet accounts. The `NotificationProvider` model already supports multiple instances per type, but the env-var config makes this impossible to use.

5. **Split config surface**: Some settings (enabled flags, operational timeouts, Zigbee2MQTT base_topic, Frigate retention) are UI-editable in the DB, while others (URLs, credentials) are env-var-only. Admins must context-switch between two configuration surfaces.

6. **`env_config.py` is a code smell**: 113 lines of boilerplate `env.str()`/`env.bool()` calls that duplicate what the settings registry and `AlarmSettingsEntry` model already provide. Every new integration requires adding more env var readers instead of leveraging the existing DB-backed settings infrastructure.

### Why encrypted DB storage is appropriate now

ADR 0075 argued that encryption was unnecessary because "if an attacker has database access, they likely have environment access too." This is not always true:

- **Database backups** are often stored, transferred, or archived separately from the runtime environment. An unencrypted DB backup leaks every integration token.
- **SQL injection or ORM bugs** could expose DB contents without granting env access.
- **Shared hosting or managed DB** scenarios mean the DB operator sees plaintext secrets.
- **Defense in depth**: Encryption at rest is a standard security practice even when the encryption key is co-located. It prevents casual exposure and satisfies security audits.

The original ADR 0038 encryption design was solid but over-engineered with per-integration wrappers. A simpler, centralized approach avoids the duplication that motivated ADR 0075's removal.

### Lessons from the original encryption implementation (ADR 0017/0038)

The pre-ADR 0075 encryption had architectural weaknesses that must not be repeated:

1. **Encryption leaked into every layer**: Views, serializers, frontend forms, and a management command all contained encrypt/decrypt/mask logic. Adding a new secret field required changes in 5+ files.
2. **Per-integration wrapper boilerplate**: Each integration had its own `encrypt_*()`, `decrypt_*()`, `mask_*()`, `prepare_runtime_*()` functions — identical patterns copy-pasted across 4 modules.
3. **Hidden runtime masking registry**: `integration_settings_masking.py` used `register_setting_masker()` calls in `apps.py` — an implicit startup dependency that broke silently if registration order changed.
4. **Encryption was optional**: Running without `SETTINGS_ENCRYPTION_KEY` was allowed, creating dual code paths (encrypted vs. plaintext) everywhere, plus a `encrypt_plaintext_secrets` management command to fix inconsistent state.
5. **No schema-driven forms**: Each integration had bespoke frontend components with hand-coded `tokenTouched` / `passwordTouched` state management.

This ADR addresses every one of these issues.

### Current credential inventory

| Integration | Env Vars | Secret Fields |
|------------|----------|---------------|
| Home Assistant | `HA_BASE_URL`, `HA_TOKEN` | `token` |
| MQTT | `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_USE_TLS`, `MQTT_TLS_INSECURE`, `MQTT_CLIENT_ID` | `password` |
| Z-Wave JS | `ZWAVEJS_WS_URL`, `ZWAVEJS_API_TOKEN` | `api_token` |
| Zigbee2MQTT | _(DB-only already)_ | _(none)_ |
| Frigate | _(DB-only already)_ | _(none)_ |
| Pushbullet | `PUSHBULLET_ACCESS_TOKEN`, + 4 more | `access_token` |
| Discord | `DISCORD_WEBHOOK_URL`, + 2 more | `webhook_url` |
| Slack | `SLACK_BOT_TOKEN`, + 3 more | `bot_token` |
| Webhook | `WEBHOOK_URL`, `WEBHOOK_AUTH_VALUE`, + 4 more | `auth_value` |

---

## Decision

Move all integration and notification provider configuration to DB-backed, UI-editable settings. Reintroduce encryption at rest for secret fields using a centralized encryption service. Remove `env_config.py` and all `*_ENABLED`, `*_TOKEN`, `*_PASSWORD`, etc. env vars.

The only integration-related env var that remains is `SETTINGS_ENCRYPTION_KEY`.

### Enabled toggles

ADR 0078 moved `enabled` flags from env vars to DB-backed UI toggles. This ADR preserves that: each integration's `enabled` boolean lives inside its `AlarmSettingsEntry` JSON blob (e.g., `{"enabled": true, "base_url": "...", "token": "enc:..."}`) and is toggled via the same UI Switch component. Notification providers keep `NotificationProvider.is_enabled` as a dedicated model field. No `*_ENABLED` env vars exist.

### 1. Centralized Encryption Service

Create `backend/alarm/crypto.py` with a focused, centralized API:

```python
# backend/alarm/crypto.py

from cryptography.fernet import Fernet

ENCRYPTED_PREFIX = "enc:v1:"

class SettingsEncryption:
    """
    Fernet-based encryption for settings stored in AlarmSettingsEntry
    and NotificationProvider JSON blobs.

    Requires SETTINGS_ENCRYPTION_KEY env var (base64-encoded 32 bytes).
    Auto-generated on first boot if not set (see ensure_encryption_key()).
    """

    _instance: "SettingsEncryption | None" = None
    _fernet: Fernet | None = None

    @classmethod
    def get(cls) -> "SettingsEncryption":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton — for tests only."""
        cls._instance = None

    def __init__(self):
        key = ensure_encryption_key()
        self._fernet = Fernet(key.encode())

    def encrypt(self, value: str) -> str:
        """Encrypt a plaintext string. Returns enc:v1:-prefixed token."""
        if not value:
            return ""
        if value.startswith(ENCRYPTED_PREFIX):
            return value  # already encrypted
        return ENCRYPTED_PREFIX + self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        """Decrypt an enc:v1:-prefixed token. Raises on failure."""
        if not value:
            return ""
        if not value.startswith(ENCRYPTED_PREFIX):
            raise ValueError(
                f"Expected encrypted value with '{ENCRYPTED_PREFIX}' prefix, "
                f"got plaintext. Run the data migration."
            )
        return self._fernet.decrypt(
            value[len(ENCRYPTED_PREFIX):].encode()
        ).decode()

    def encrypt_fields(self, config: dict, fields: list[str]) -> dict:
        """Encrypt specified fields in a config dict. Returns a copy."""
        result = config.copy()
        for field in fields:
            if field in result and result[field]:
                result[field] = self.encrypt(str(result[field]))
        return result

    def decrypt_fields(self, config: dict, fields: list[str]) -> dict:
        """Decrypt specified fields in a config dict. Returns a copy."""
        result = config.copy()
        for field in fields:
            if field in result and result[field]:
                result[field] = self.decrypt(str(result[field]))
        return result

    def mask_fields(self, config: dict, fields: list[str]) -> dict:
        """Replace secret fields with has_<field> booleans. Returns a copy."""
        result = config.copy()
        for field in fields:
            raw = result.pop(field, "")
            has_value = bool(raw) and raw != ""
            result[f"has_{field}"] = has_value
        return result
```

Key design choices vs. the original implementation:

- **Versioned prefix `enc:v1:`** — if we ever change algorithms (Fernet → AES-GCM, key rotation), we introduce `enc:v2:` without a flag-day migration. The original used bare `enc:` with no upgrade path.
- **Encryption is mandatory** — `__init__` calls `ensure_encryption_key()` which auto-generates a key if none exists. There is no `can_encrypt()` check, no "encryption unavailable" fallback, no dual code paths. If the key is missing and can't be generated, startup fails hard.
- **No plaintext passthrough on decrypt** — the original silently accepted plaintext values, which meant you could never be sure if a value was actually encrypted. Now, encountering plaintext in a secret field is an error that points to the data migration. This eliminates the need for the old `encrypt_plaintext_secrets` management command.
- **`reset()` classmethod for tests** — avoids the need to monkey-patch internals in every test file.
- **No per-integration wrappers** — integrations don't define their own `encrypt_*` / `decrypt_*` functions. The encrypted fields are declared in the settings registry (see below).

### 2. Encrypted Fields and Config Schema in the Settings Registry

The original implementation scattered encrypted field declarations across per-integration `config.py` files and required a runtime masking registry with `register_setting_masker()` calls in `apps.py`. This time, declare everything statically in the settings registry:

```python
# settings_registry.py — new fields on SettingDefinition

@dataclass(frozen=True)
class SettingDefinition:
    key: str
    name: str
    value_type: str
    default: object
    description: str = ""
    deprecated: bool = False
    deprecation_message: str = ""
    encrypted_fields: list[str] = field(default_factory=list)   # NEW
    config_schema: dict | None = None                            # NEW
```

- **`encrypted_fields`** — declares which keys within the JSON blob are secrets. Replaces per-integration `*_ENCRYPTED_FIELDS` constants, the `integration_settings_masking.py` registry, and the `register_setting_masker()` startup calls. One source of truth, statically defined, no runtime registration.
- **`config_schema`** — JSON Schema describing the setting's shape, field types, titles, and descriptions. The frontend reads this from the API and renders forms dynamically. Replaces bespoke per-integration settings components.

```python
# settings_registry.py — updated entries

SettingDefinition(
    key="home_assistant",
    name="Home Assistant",
    value_type=SystemConfigValueType.JSON,
    default={
        "enabled": False,
        "base_url": "http://localhost:8123",
        "token": "",
        "connect_timeout_seconds": 2,
    },
    description="Home Assistant connection and operational settings.",
    encrypted_fields=["token"],
    config_schema={
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean", "title": "Enabled"},
            "base_url": {
                "type": "string",
                "title": "Base URL",
                "format": "url",
                "description": "Home Assistant instance URL",
            },
            "token": {
                "type": "string",
                "title": "Long-Lived Access Token",
                "secret": True,
                "description": "Generate at Profile → Security → Long-lived access tokens",
            },
            "connect_timeout_seconds": {
                "type": "number",
                "title": "Connect Timeout (seconds)",
                "minimum": 1,
                "maximum": 30,
            },
        },
    },
),

SettingDefinition(
    key="mqtt",
    name="MQTT",
    value_type=SystemConfigValueType.JSON,
    default={
        "enabled": False,
        "host": "localhost",
        "port": 1883,
        "username": "",
        "password": "",
        "use_tls": False,
        "tls_insecure": False,
        "client_id": "latchpoint-alarm",
        "keepalive_seconds": 30,
        "connect_timeout_seconds": 5,
    },
    description="MQTT broker connection and operational settings.",
    encrypted_fields=["password"],
    config_schema={
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean", "title": "Enabled"},
            "host": {"type": "string", "title": "Host"},
            "port": {"type": "integer", "title": "Port", "minimum": 1, "maximum": 65535},
            "username": {"type": "string", "title": "Username"},
            "password": {"type": "string", "title": "Password", "secret": True},
            "use_tls": {"type": "boolean", "title": "Use TLS"},
            "tls_insecure": {"type": "boolean", "title": "TLS Insecure (skip verify)"},
            "client_id": {"type": "string", "title": "Client ID"},
            "keepalive_seconds": {"type": "integer", "title": "Keepalive (seconds)", "minimum": 5},
            "connect_timeout_seconds": {"type": "integer", "title": "Connect Timeout (seconds)", "minimum": 1},
        },
    },
),

SettingDefinition(
    key="zwavejs",
    name="Z-Wave JS",
    value_type=SystemConfigValueType.JSON,
    default={
        "enabled": False,
        "ws_url": "ws://localhost:3000",
        "api_token": "",
        "connect_timeout_seconds": 5,
        "reconnect_min_seconds": 1,
        "reconnect_max_seconds": 30,
    },
    description="Z-Wave JS WebSocket connection and operational settings.",
    encrypted_fields=["api_token"],
    config_schema={
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean", "title": "Enabled"},
            "ws_url": {"type": "string", "title": "WebSocket URL", "format": "uri"},
            "api_token": {"type": "string", "title": "API Token", "secret": True},
            "connect_timeout_seconds": {"type": "integer", "title": "Connect Timeout (seconds)", "minimum": 1},
            "reconnect_min_seconds": {"type": "integer", "title": "Reconnect Min (seconds)", "minimum": 1},
            "reconnect_max_seconds": {"type": "integer", "title": "Reconnect Max (seconds)", "minimum": 1},
        },
    },
),
```

Zigbee2MQTT and Frigate entries already exist in the registry with all their fields. They have no secret fields, so `encrypted_fields` stays empty. Add `config_schema` to them for schema-driven forms.

Notification handler encrypted fields remain on the handler class (since notification providers are per-row model instances, not registry settings):

```python
class PushbulletHandler(NotificationHandler):
    encrypted_fields = ["access_token"]
    # config_schema already exists on handlers — no change needed

class DiscordHandler(NotificationHandler):
    encrypted_fields = ["webhook_url"]

class SlackHandler(NotificationHandler):
    encrypted_fields = ["bot_token"]

class WebhookHandler(NotificationHandler):
    encrypted_fields = ["auth_value"]
```

### 3. Encrypt/Decrypt at the Model Layer

The original implementation scattered `encrypt_config()` / `mask_config()` calls across every view and serializer. This time, push encryption down to `AlarmSettingsEntry` model methods so views and internal consumers never deal with `enc:v1:` prefixes directly:

```python
# backend/alarm/models.py — new methods on AlarmSettingsEntry

class AlarmSettingsEntry(models.Model):
    # ... existing fields ...

    def get_decrypted_value(self) -> dict:
        """Internal read path — returns plaintext config for runtime consumers."""
        definition = ALARM_PROFILE_SETTINGS_BY_KEY.get(self.key)
        if not definition or not definition.encrypted_fields:
            return self.value
        crypto = SettingsEncryption.get()
        return crypto.decrypt_fields(self.value, definition.encrypted_fields)

    def get_masked_value(self) -> dict:
        """API read path — replaces secrets with has_* booleans."""
        definition = ALARM_PROFILE_SETTINGS_BY_KEY.get(self.key)
        if not definition or not definition.encrypted_fields:
            return self.value
        crypto = SettingsEncryption.get()
        return crypto.mask_fields(self.value, definition.encrypted_fields)

    def set_value_with_encryption(self, data: dict, partial: bool = True) -> None:
        """
        Write path — merges incoming data, encrypts secrets, saves.

        Handles "keep existing secret" semantics: if a secret field is
        absent or empty in `data`, the existing encrypted value is preserved.
        """
        definition = ALARM_PROFILE_SETTINGS_BY_KEY.get(self.key)
        current = self.value or {}

        if partial:
            updated = {**current, **data}
        else:
            updated = data

        if definition and definition.encrypted_fields:
            crypto = SettingsEncryption.get()
            for field in definition.encrypted_fields:
                if field not in data or data[field] == "":
                    # Keep existing encrypted value
                    updated[field] = current.get(field, "")
                else:
                    updated[field] = crypto.encrypt(data[field])

        self.value = updated
        self.save(update_fields=["value", "updated_at"])
```

This means integration views become thin:

```python
# Example: Home Assistant settings view — no crypto imports needed
class HomeAssistantSettingsView(APIView):
    def get(self, request):
        entry = get_profile_entry("home_assistant")
        return Response(entry.get_masked_value())

    def patch(self, request):
        entry = get_profile_entry("home_assistant")
        entry.set_value_with_encryption(request.data)
        settings_profile_changed.send(sender=self.__class__, key="home_assistant")
        return Response(entry.get_masked_value())
```

Internal consumers (gateways, connection managers) call `entry.get_decrypted_value()` and receive plaintext — they never import `SettingsEncryption` or know about encryption at all.

### 4. Notification Provider Config Back in DB

The `NotificationProvider.config` JSONField stores the full provider configuration again, with secret fields encrypted. Add similar helper methods to the model:

```python
# backend/notifications/models.py — new methods on NotificationProvider

class NotificationProvider(models.Model):
    # ... existing fields ...

    def get_decrypted_config(self) -> dict:
        """Runtime dispatch path — returns plaintext config."""
        handler = get_handler(self.provider_type)
        if not handler.encrypted_fields:
            return self.config
        crypto = SettingsEncryption.get()
        return crypto.decrypt_fields(self.config, handler.encrypted_fields)

    def get_masked_config(self) -> dict:
        """API response path — replaces secrets with has_* booleans."""
        handler = get_handler(self.provider_type)
        if not handler.encrypted_fields:
            return self.config
        crypto = SettingsEncryption.get()
        return crypto.mask_fields(self.config, handler.encrypted_fields)

    def set_config_with_encryption(self, data: dict, partial: bool = True) -> None:
        """Write path — encrypts secrets before saving."""
        handler = get_handler(self.provider_type)
        current = self.config or {}

        if partial:
            updated = {**current, **data}
        else:
            updated = data

        if handler.encrypted_fields:
            crypto = SettingsEncryption.get()
            for field in handler.encrypted_fields:
                if field not in data or data[field] == "":
                    updated[field] = current.get(field, "")
                else:
                    updated[field] = crypto.encrypt(data[field])

        self.config = updated
        self.save(update_fields=["config", "updated_at"])
```

This restores multi-instance support — users can create multiple Discord webhooks, multiple Pushbullet accounts, etc. Views and serializers call model methods instead of importing crypto directly.

### 5. Connection Test Before Save

The original implementation saved credentials blindly. Add a `test-connection` endpoint per integration that validates credentials before persisting:

```
POST /api/alarm/home-assistant/test-connection/
{"base_url": "http://homeassistant.local:8123", "token": "eyJ..."}
→ {"status": "ok", "version": "2024.12.1"}

POST /api/alarm/mqtt/test-connection/
{"host": "mqtt.local", "port": 1883, "username": "lp", "password": "..."}
→ {"status": "ok"}

POST /api/alarm/zwavejs/test-connection/
{"ws_url": "ws://localhost:3000", "api_token": "..."}
→ {"status": "ok", "server_version": "1.35.0"}

# Error response
→ {"status": "error", "detail": "401 Unauthorized — invalid access token"}
```

These endpoints accept plaintext credentials (not yet encrypted), make a real connection attempt, and return the result. The frontend calls test first, then PATCH to persist. This prevents saving broken credentials and gives immediate feedback during setup.

The test endpoint does **not** store anything — it is a pure validation call. Credentials are only persisted through the PATCH endpoint.

### 6. Remove `env_config.py` and Env Var Dependencies

Delete entirely:

| File / Code | Action |
|-------------|--------|
| `backend/alarm/env_config.py` | **Delete** — all 11 `get_*_config()` functions removed |
| `backend/notifications/provider_registry.py` | **Delete** — env-based auto-provisioning no longer needed |
| `.env.example` integration vars | **Remove** all `HA_*`, `MQTT_*`, `ZWAVEJS_*`, `ZIGBEE2MQTT_*`, `FRIGATE_*`, `PUSHBULLET_*`, `DISCORD_*`, `SLACK_*`, `WEBHOOK_*`, `HA_NOTIFY_*` vars |
| `.env.example` | **Add** `SETTINGS_ENCRYPTION_KEY=` with generation instructions |
| Handler `from_env()` methods | **Remove** from all notification handlers |
| Handler `is_enabled_from_env()` / `is_configured_from_env()` | **Remove** from all notification handlers |

### 7. Schema-Driven Frontend Forms

The original implementation had bespoke React components for each integration (`HomeAssistantConnectionCard.tsx`, `MqttSettingsForm.tsx`, etc.), each with hand-coded `tokenTouched` / `passwordTouched` state management. This time, build **one generic `IntegrationSettingsForm` component** that renders from the `config_schema`:

```
GET /api/alarm/settings/registry/
→ [
    {
      "key": "home_assistant",
      "name": "Home Assistant",
      "config_schema": {
        "properties": {
          "base_url": {"type": "string", "title": "Base URL", "format": "url"},
          "token": {"type": "string", "title": "Access Token", "secret": true},
          ...
        }
      },
      "encrypted_fields": ["token"]
    },
    ...
  ]
```

The generic form component:
- Reads `config_schema.properties` to render the correct input type (text, number, boolean toggle, password)
- Uses `"secret": true` in the schema to render password inputs with "A value is saved" / "Clear" UX
- Reads `encrypted_fields` to know which fields use the saved/clear pattern
- Calls the `test-connection` endpoint before saving (if available for that integration)
- Works identically for all integrations — adding a new integration = adding a registry entry, zero frontend code

Notification providers already have `config_schema` on their handlers and use this same pattern for the `AddEditProviderDialog`.

| Component | Changes |
|-----------|---------|
| `IntegrationSettingsForm` (new) | Generic schema-driven form component, used by all integration tabs |
| `HomeAssistantSettingsTab` | Replace bespoke form with `<IntegrationSettingsForm settingKey="home_assistant" />` |
| `MqttSettingsTab` | Replace bespoke form with `<IntegrationSettingsForm settingKey="mqtt" />` |
| `ZwaveJsSettingsTab` | Replace bespoke read-only display with `<IntegrationSettingsForm settingKey="zwavejs" />` |
| `NotificationsTab` | Restore `AddEditProviderDialog` with schema-driven fields. Support multiple providers of same type. |
| `FrigateSettingsTab` | Can adopt `IntegrationSettingsForm` — already UI-editable, no credential fields |
| `Zigbee2mqttSettingsTab` | Can adopt `IntegrationSettingsForm` — already UI-editable, no credential fields |

### 8. Audit Logging for Credential Changes

The original had no visibility into when or who changed credentials. Add event log entries when secret fields are modified:

```python
# Inside set_value_with_encryption / set_config_with_encryption
for field in encrypted_fields:
    if field in data and data[field] != "":
        log_event(
            event_type="credential_updated",
            detail=f"{setting_key}.{field} updated",
            user=request.user,
        )
    elif field in data and data[field] == "" and current.get(field):
        log_event(
            event_type="credential_cleared",
            detail=f"{setting_key}.{field} cleared",
            user=request.user,
        )
```

Logs record **that** a credential changed and **who** changed it — never the credential value itself. These appear in the Events page alongside other system events.

### 9. Setup Wizard Enhancement

The existing setup flow should guide new users through initial integration configuration:

1. Encryption key auto-generated on first boot (transparent to user)
2. Configure Home Assistant (URL + token) with connection test
3. Configure MQTT broker (host, port, credentials) with connection test
4. Optionally configure Z-Wave JS, Zigbee2MQTT, Frigate
5. Optionally configure notification providers

Each step uses the same `IntegrationSettingsForm` component with the `test-connection` button.

### 10. Auto-Generate Encryption Key on First Boot

To avoid requiring users to manually generate `SETTINGS_ENCRYPTION_KEY`:

```python
# backend/alarm/crypto.py

import os
from pathlib import Path

_KEY_FILE = Path(os.environ.get("DATA_DIR", "/data")) / ".encryption_key"

def ensure_encryption_key() -> str:
    """
    Return the encryption key, generating one if needed.

    Resolution order:
    1. SETTINGS_ENCRYPTION_KEY env var (explicit operator choice)
    2. Persisted key file in data volume (auto-generated on first boot)
    3. Generate new key → write to key file → return it

    Raises RuntimeError if the key file directory doesn't exist (misconfigured volume).
    """
    # 1. Explicit env var takes priority
    key = os.environ.get("SETTINGS_ENCRYPTION_KEY", "")
    if key:
        return key

    # 2. Previously auto-generated key
    if _KEY_FILE.exists():
        return _KEY_FILE.read_text().strip()

    # 3. First boot — generate and persist
    if not _KEY_FILE.parent.exists():
        raise RuntimeError(
            f"Data directory {_KEY_FILE.parent} does not exist. "
            "Mount a persistent volume or set SETTINGS_ENCRYPTION_KEY."
        )
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    _KEY_FILE.write_text(key)
    return key
```

This means zero-config first boot: the key is generated and persisted in the data volume. Users who want explicit control can still set `SETTINGS_ENCRYPTION_KEY` in their env.

### 11. Startup Validation

On application startup (in `alarm/apps.py` `ready()`), verify that existing encrypted values can be decrypted with the current key:

```python
def _validate_encryption_key():
    """
    Spot-check one encrypted value to verify the key is correct.
    Prevents silent data loss from key rotation or misconfiguration.
    """
    from alarm.crypto import SettingsEncryption, ENCRYPTED_PREFIX

    crypto = SettingsEncryption.get()
    # Find any AlarmSettingsEntry with an encrypted value
    for entry in AlarmSettingsEntry.objects.all():
        if not isinstance(entry.value, dict):
            continue
        for v in entry.value.values():
            if isinstance(v, str) and v.startswith(ENCRYPTED_PREFIX):
                try:
                    crypto.decrypt(v)
                    return  # Key works
                except Exception:
                    raise RuntimeError(
                        "SETTINGS_ENCRYPTION_KEY cannot decrypt existing values. "
                        "The key may have been rotated or lost. "
                        "Restore the original key or re-configure credentials."
                    )
```

This catches key loss at startup instead of at runtime when a gateway tries to connect and silently fails.

### 12. Test Helpers

The original required monkey-patching `SETTINGS_ENCRYPTION_KEY` and `SettingsEncryption._instance` in every test file. Provide a reusable mixin:

```python
# backend/alarm/test_helpers.py

import os
from cryptography.fernet import Fernet

# Deterministic test key — never used in production
TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()

class EncryptionTestMixin:
    """Mixin for tests that need encryption. Sets up and tears down a test key."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ["SETTINGS_ENCRYPTION_KEY"] = TEST_ENCRYPTION_KEY
        SettingsEncryption.reset()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("SETTINGS_ENCRYPTION_KEY", None)
        SettingsEncryption.reset()
        super().tearDownClass()
```

Tests that need encryption inherit from `EncryptionTestMixin` — one line, no boilerplate.

### 13. Data Migration

A Django migration handles the transition from env-var-based config to DB-backed config:

1. **Read current env vars** (if present) and write them as encrypted `AlarmSettingsEntry` values
2. **Read notification handler `from_env()` configs** and write them into `NotificationProvider.config` (encrypted)
3. **Preserve existing `enabled` state** from DB (ADR 0078 already moved this)
4. **Log what was migrated** for operator visibility

This migration is idempotent — running it again with the same env vars produces the same DB state.

---

## Migration Path

### Phase 1: Encryption Infrastructure
- Create `backend/alarm/crypto.py` with `SettingsEncryption` class and `ensure_encryption_key()`
- Add `cryptography` package to dependencies
- Add `encrypted_fields` and `config_schema` fields to `SettingDefinition`
- Extend settings registry entries with connection fields, schemas, and encrypted field lists
- Add `EncryptionTestMixin` to `backend/alarm/test_helpers.py`
- Add startup validation in `alarm/apps.py`

### Phase 2: Model-Layer Encryption
- Add `get_decrypted_value()`, `get_masked_value()`, `set_value_with_encryption()` to `AlarmSettingsEntry`
- Add `get_decrypted_config()`, `get_masked_config()`, `set_config_with_encryption()` to `NotificationProvider`
- Add `encrypted_fields` class attribute to each notification handler
- Add audit log entries for credential changes

### Phase 3: Backend Endpoints
- Convert integration PATCH endpoints to accept full config via model methods
- Add `test-connection` endpoints for HA, MQTT, Z-Wave JS
- Add `/api/alarm/settings/registry/` endpoint exposing schemas to frontend
- Update notification provider CRUD to use model encryption methods
- Remove `from_env()` and `is_configured_from_env()` from handlers
- Write data migration to import env vars into DB

### Phase 4: Frontend
- Build generic `IntegrationSettingsForm` component driven by `config_schema`
- Replace bespoke integration settings components with schema-driven form
- Restore `AddEditProviderDialog` for notification providers
- Add connection test buttons using `test-connection` endpoints
- Update setup wizard

### Phase 5: Remove Env Var Infrastructure
- Delete `backend/alarm/env_config.py`
- Delete `backend/notifications/provider_registry.py`
- Remove integration env vars from `.env.example` (keep `SETTINGS_ENCRYPTION_KEY`)
- Update deployment docs and `docker-compose.yml`

### Phase 6: Supersede ADRs
- Mark [ADR 0075](0075-env-var-credentials-remove-encryption.md) as **Superseded by 0079**
- Mark [ADR 0078](0078-integration-enabled-ui-toggle.md) as **Incorporated into 0079** (enabled flags remain DB-backed, this ADR extends the pattern to all config)

---

## Alternatives Considered

### 1. Keep Env Vars for Credentials, Only Restore Notification Provider UI
**Rejected**: Addresses the multi-instance notification problem but doesn't solve setup friction, credential rotation requiring restart, or the split config surface. Half-measures create more inconsistency.

### 2. Support Both Env Vars and UI (Env Overrides DB)
**Rejected**: Creates confusion about which config surface is authoritative. The "env overrides DB" pattern was exactly what ADR 0078 removed for `enabled` flags because UI edits were silently discarded.

### 3. Use Django's `SECRET_KEY` for Encryption Instead of Separate Key
**Rejected**: Django's `SECRET_KEY` is used for session signing and CSRF tokens. Using it for settings encryption conflates two security domains. If `SECRET_KEY` is rotated (as Django recommends periodically), all encrypted settings become unreadable.

### 4. Use `django-encrypted-model-fields` or `django-fernet-fields`
**Considered**: These encrypt entire model fields rather than specific keys within a JSON blob. Since `AlarmSettingsEntry.value` is a JSONField containing both secret and non-secret keys, per-field encryption within the JSON is more appropriate. A dedicated `SettingsEncryption` service is simpler and avoids the dependency.

### 5. External Secret Manager (Vault, SOPS)
**Rejected**: Overkill for a self-hosted alarm system. Adds operational complexity and external dependencies that most home users won't have.

---

## Consequences

### Positive
- **Zero env vars for integration config**: First boot only needs `DATABASE_URL` — `SETTINGS_ENCRYPTION_KEY` is auto-generated
- **Full UI-driven setup**: New users can configure everything from the browser
- **Credential rotation without restart**: Change an HA token or MQTT password from the settings page
- **Connection testing before save**: Validates credentials work before persisting — no more saving broken config
- **Multi-profile isolation**: Different `AlarmSettingsProfile` instances can have different HA tokens, MQTT brokers, etc.
- **Multi-instance notification providers**: Multiple Discord webhooks, multiple Pushbullet accounts, etc.
- **Defense in depth**: Secrets encrypted at rest in DB backups with versioned `enc:v1:` prefix for future algorithm changes
- **Single config surface**: Everything in one place (the UI), no split between env files and settings pages
- **Simpler deployment docs**: No 30+ env vars to document and explain
- **Schema-driven forms**: One generic `IntegrationSettingsForm` component replaces bespoke per-integration components. Adding a new integration requires zero frontend code.
- **Audit trail**: Credential changes are logged to the event system with user attribution
- **Startup validation**: Detects encryption key loss/mismatch at boot, not at runtime

### Negative
- **`SETTINGS_ENCRYPTION_KEY` management**: Users who back up the database must also back up the auto-generated key file in the data volume (or their explicit env var). Documented in deployment guide.
- **Encryption overhead**: Fernet encrypt/decrypt on every settings read/write. Negligible for the low frequency of settings access.
- **Re-adds crypto code**: The `SettingsEncryption` class and model methods (~100 lines total). Significantly less than the original ~200+ lines because: no per-integration wrappers, no masking registry, no management command, encryption lives at the model layer not scattered across views/serializers.
- **Migration effort**: Existing deployments must run the data migration. Env vars are consumed once during migration and can then be removed.

### Neutral
- `AlarmSettingsEntry` model gets three new methods but no schema changes — same JSON blob storage, just with encrypted values in secret fields
- `NotificationProvider` model gets three new methods — `config` JSONField usage changes from "empty (env-sourced)" back to "stores actual config (encrypted)"
- TOTP secrets in `UserTOTPDevice.secret_encrypted` are **not affected**
- User alarm PIN hashes in `UserCode.code_hash` are **not affected**
- Signal handlers for runtime reconnection (from ADR 0078) remain unchanged

---

## Supersedes

- [ADR 0075: Move Integration Credentials to Environment Variables and Remove Encryption](0075-env-var-credentials-remove-encryption.md) — **Superseded**: credentials move back to DB with encryption
- [ADR 0078: Move Integration Enabled Flags to UI Toggle](0078-integration-enabled-ui-toggle.md) — **Incorporated**: enabled flags remain DB-backed; this ADR extends the pattern to all config

## References

- [ADR 0017: Home Assistant Connection Settings (Encrypted)](0017-home-assistant-connection-settings-in-profile.md) — Original DB-encrypted approach
- [ADR 0038: Centralized Encryption Logic](0038-centralized-encryption-logic.md) — Original centralized encryption design
- [ADR 0044: Notifications Architecture (Consolidated)](0044-notifications-architecture-consolidation.md)
- Settings registry: `backend/alarm/settings_registry.py`
- Current env config: `backend/alarm/env_config.py` (to be deleted)
- Current provider registry: `backend/notifications/provider_registry.py` (to be deleted)
