# ADR 0038: Centralized Encryption Logic

## Status
**Implemented**

## Context

The codebase currently has encryption logic spread across multiple locations with significant duplication:

### Current State

**1. Core Encryption (`backend/alarm/crypto.py`)**
- Low-level primitives: `encrypt_secret()`, `decrypt_secret()`, `can_encrypt()`
- Uses Fernet symmetric encryption with the `SETTINGS_ENCRYPTION_KEY` env var
- Uses the `enc:` prefix convention for stored encrypted values
- Intended to be the foundation all other encryption builds upon

**2. Notifications Encryption (`backend/notifications/encryption.py`)**
- Higher-level config helpers: `encrypt_config()`, `decrypt_config()`, `mask_config()`
- Operates on dictionaries with a list of encrypted field names
- Only used by the notifications module today

**3. Integration-Specific Wrappers (duplicated pattern)**

Each integration has nearly identical wrapper functions:

| Integration | File | Functions |
|------------|------|-----------|
| Home Assistant | `backend/integrations_home_assistant/config.py` | `encrypt_home_assistant_token()`, `decrypt_home_assistant_token()`, `mask_home_assistant_connection()`, `prepare_runtime_home_assistant_connection()` |
| Z-Wave JS | `backend/integrations_zwavejs/config.py` | `encrypt_zwavejs_api_token()`, `decrypt_zwavejs_api_token()`, `mask_zwavejs_connection()`, `prepare_runtime_zwavejs_connection()` |
| Zigbee2MQTT | `backend/integrations_zigbee2mqtt/config.py` | `mask_zigbee2mqtt_settings()` |
| MQTT | `backend/transports_mqtt/config.py` | `encrypt_mqtt_password()`, `decrypt_mqtt_password()`, `mask_mqtt_connection()`, `prepare_runtime_mqtt_connection()` |

### The Repeated Pattern

Every integration implements the same boilerplate:

```python
def encrypt_<secret>(plain: object) -> str:
    if plain is None:
        return ""
    plain_str = str(plain)
    if plain_str == "":
        return ""
    return encrypt_secret(plain_str)

def decrypt_<secret>(stored: object) -> str:
    if stored is None:
        return ""
    stored_str = str(stored)
    if stored_str == "":
        return ""
    return decrypt_secret(stored_str)

def mask_<settings>(raw: object) -> dict:
    # Replace secret field with has_<field> boolean
    ...

def prepare_runtime_<config>(raw: object) -> dict:
    # Normalize and decrypt secrets for runtime use
    ...
```

### Problems with Current Approach

1. **Duplication**: Same logic repeated 4+ times across integrations
2. **Inconsistent API**: Each integration uses slightly different function signatures
3. **Scattered Location**: `backend/notifications/encryption.py` has general-purpose helpers that would benefit other modules
4. **Maintenance Burden**: Changes to encryption logic require updates in multiple files
5. **Testing Overhead**: Each module tests its own copy of essentially identical code
6. **Behavior Drift Risk**: Masking and “empty secret” handling can subtly diverge between integrations

## Decision

Centralize all config-level encryption helpers in `backend/alarm/crypto.py`, then refactor integrations and notifications to use the shared API.

### 1. Extend `backend/alarm/crypto.py` with Config-Level Helpers

Move and generalize the config-level encryption utilities from `backend/notifications/encryption.py` to `backend/alarm/crypto.py`:

```python
# backend/alarm/crypto.py (extended)

def encrypt_config(config: dict, encrypted_fields: list[str]) -> dict:
    """
    Encrypt sensitive fields in a configuration dictionary.

    Args:
        config: Configuration dictionary
        encrypted_fields: List of field names that contain secrets

    Returns:
        Copy of config with specified fields encrypted (prefixed with 'enc:')
    """
    ...

def decrypt_config(config: dict, encrypted_fields: list[str]) -> dict:
    """
    Decrypt sensitive fields in a configuration dictionary.

    Returns:
        Copy of config with specified fields decrypted
    """
    ...

def mask_config(config: dict, encrypted_fields: list[str]) -> dict:
    """
    Mask sensitive fields for API responses.

    Replaces `field` with `has_field` boolean indicator.

    Returns:
        Copy of config with sensitive fields replaced by has_* booleans
    """
    ...

def prepare_runtime_config(
    raw: object,
    *,
    encrypted_fields: list[str],
    defaults: dict[str, object],
) -> dict:
    """
    Prepare a configuration for runtime use.

    Normalizes against defaults and decrypts sensitive fields.

    Behavioral requirements:
    - `raw` may be `None` or not a `dict`; treat as empty
    - Only allow keys present in `defaults` (drop unknown keys)
    - Treat `None` and `""` as empty secrets (stored and runtime value: `""`)
    - Do not double-encrypt values already prefixed with `enc:`

    Returns:
        Normalized config with secrets decrypted
    """
    ...
```

### 2. Define Encrypted Fields as Constants

Each integration module defines its encrypted fields as a constant:

```python
# backend/integrations_home_assistant/config.py

HOME_ASSISTANT_ENCRYPTED_FIELDS = ["token"]

DEFAULT_HOME_ASSISTANT_CONNECTION = {
    "enabled": False,
    "base_url": "http://localhost:8123",
    "token": "",
    "connect_timeout_seconds": 2,
}
```

### 3. Simplify Integration Config Modules

Replace verbose wrapper functions with thin helpers using the centralized API:

```python
# backend/integrations_home_assistant/config.py (after)

from alarm.crypto import (
    decrypt_config,
    encrypt_config,
    mask_config,
    prepare_runtime_config,
)

HOME_ASSISTANT_ENCRYPTED_FIELDS = ["token"]

DEFAULT_HOME_ASSISTANT_CONNECTION = {
    "enabled": False,
    "base_url": "http://localhost:8123",
    "token": "",
    "connect_timeout_seconds": 2,
}


def mask_home_assistant_connection(raw: object) -> dict:
    """Return a safe-for-API view of connection settings."""
    config = _normalize(raw)
    return mask_config(config, HOME_ASSISTANT_ENCRYPTED_FIELDS)


def prepare_runtime_home_assistant_connection(raw: object) -> dict:
    """Prepare connection settings for runtime use."""
    return prepare_runtime_config(
        raw,
        encrypted_fields=HOME_ASSISTANT_ENCRYPTED_FIELDS,
        defaults=DEFAULT_HOME_ASSISTANT_CONNECTION,
    )


def _normalize(raw: object) -> dict:
    """Normalize raw settings to expected shape."""
    base = DEFAULT_HOME_ASSISTANT_CONNECTION.copy()
    if isinstance(raw, dict):
        base.update({k: v for k, v in raw.items() if k in base})
    return base
```

Notes:
- Each integration keeps its own defaults/normalization (schema differs per integration).
- Integrations should avoid creating one-off `encrypt_*` / `decrypt_*` wrappers unless they add non-trivial behavior.

### 4. Update `backend/notifications/encryption.py` to Re-Export

For backward compatibility, make `notifications/encryption.py` a thin re-export layer:

```python
# backend/notifications/encryption.py

"""
Encryption utilities for notification provider configurations.

Re-exports from alarm.crypto for backward compatibility.
"""

from alarm.crypto import decrypt_config, encrypt_config, mask_config

__all__ = ["encrypt_config", "decrypt_config", "mask_config"]
```

---

## Module Structure After Change

```
backend/
├── alarm/
│   ├── crypto.py              # Core + config-level encryption (EXPANDED)
│   │   ├── encrypt_secret()
│   │   ├── decrypt_secret()
│   │   ├── can_encrypt()
│   │   ├── encrypt_config()   # NEW
│   │   ├── decrypt_config()   # NEW
│   │   ├── mask_config()      # NEW
│   │   └── prepare_runtime_config()  # NEW
│   └── ...
│
├── notifications/
│   ├── encryption.py          # Re-exports from alarm.crypto
│   └── ...
│
├── integrations_home_assistant/
│   └── config.py              # Uses alarm.crypto, defines ENCRYPTED_FIELDS
│
├── integrations_zwavejs/
│   └── config.py              # Uses alarm.crypto, defines ENCRYPTED_FIELDS
│
├── integrations_zigbee2mqtt/
│   └── config.py              # Uses alarm.crypto, defines ENCRYPTED_FIELDS
│
└── transports_mqtt/
    └── config.py              # Uses alarm.crypto, defines ENCRYPTED_FIELDS
```

---

## API Reference

### Core Functions (unchanged)

| Function | Purpose |
|----------|---------|
| `encrypt_secret(value: str) -> str` | Encrypt single value, returns `enc:`-prefixed token |
| `decrypt_secret(value: str) -> str` | Decrypt `enc:`-prefixed value, passes through plaintext |
| `can_encrypt() -> bool` | Check if encryption is configured |

### Config Functions (new in `alarm/crypto`)

| Function | Purpose |
|----------|---------|
| `encrypt_config(config, fields) -> dict` | Encrypt specified fields in a config dict |
| `decrypt_config(config, fields) -> dict` | Decrypt specified fields in a config dict |
| `mask_config(config, fields) -> dict` | Replace sensitive fields with `has_*` booleans |
| `prepare_runtime_config(raw, *, encrypted_fields, defaults) -> dict` | Normalize + decrypt for runtime use |

---

## Migration Path

This change should not require data migrations: encrypted values remain `enc:`-prefixed strings, and `decrypt_secret()` already supports plaintext for backward compatibility.

### Phase 1: Add Functions to `backend/alarm/crypto.py`
- Add `encrypt_config()`, `decrypt_config()`, `mask_config()`, `prepare_runtime_config()`
- Add comprehensive tests

### Phase 2: Update `backend/notifications/encryption.py`
- Change to re-export from `alarm.crypto`
- Maintain backward compatibility

### Phase 3: Refactor Integration Config Modules
- Update `integrations_home_assistant/config.py`
- Update `integrations_zwavejs/config.py`
- Update `integrations_zigbee2mqtt/config.py`
- Update `transports_mqtt/config.py`
- Remove duplicate encrypt/decrypt wrapper functions
- Define `*_ENCRYPTED_FIELDS` constants

### Phase 4: Update Tests
- Consolidate encryption tests to `alarm/tests/test_crypto.py`
- Remove redundant per-module encryption tests

---

## Alternatives Considered

### 1. Keep Current Structure
**Rejected**: Duplication is already causing maintenance overhead and will worsen as more integrations are added.

### 2. Create Separate `encryption` Django App
**Rejected**: Overkill for what is essentially utility functions. The `alarm` app is the natural home for core infrastructure.

### 3. Use Decorator/Mixin Pattern
**Considered**: Could create a `@encrypted_fields(["token"])` decorator for serializers.
**Deferred**: Can be added later on top of the centralized functions if needed.

### 4. Move All Config to a Central Model
**Rejected**: Would require significant architectural changes. Current profile-based JSON settings work well.

---

## Consequences

### Positive
- **Single source of truth** for encryption logic
- **Reduced duplication** across 4+ modules
- **Consistent API** for all encryption operations
- **Easier testing** with one comprehensive test suite
- **Simpler onboarding** for new integrations

### Negative
- **Migration effort** to update existing modules
- **Import path change** for existing code (mitigated by re-exports)

### Neutral
- No change to encryption algorithm or security model
- No change to stored data format (`enc:` prefix)
- No change to `SETTINGS_ENCRYPTION_KEY` environment variable

---

## Todos

- Implement the config helpers in `backend/alarm/crypto.py`.
- Refactor integrations to use config helpers and constants (`*_ENCRYPTED_FIELDS`).
- Replace `backend/notifications/encryption.py` with a compatibility re-export.
- Consolidate and de-duplicate tests under `backend/alarm/tests/`.
- Decide whether settings writes that include secrets should be rejected when `can_encrypt()` is false (to avoid unintentionally storing plaintext).

## References

- [ADR 0017: Home Assistant Connection Settings (Encrypted)](0017-home-assistant-connection-settings-in-profile.md)
- [ADR 0037: Notifications Django App Architecture](0037-notifications-django-app-architecture.md)
- Current implementation: `backend/alarm/crypto.py`
- Current implementation: `backend/notifications/encryption.py`
