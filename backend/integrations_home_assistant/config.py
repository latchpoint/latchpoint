from __future__ import annotations

from copy import deepcopy

from alarm.crypto import mask_config, prepare_runtime_config

DEFAULT_HOME_ASSISTANT_CONNECTION: dict[str, object] = {
    "enabled": False,
    "base_url": "http://localhost:8123",
    "token": "",
    "connect_timeout_seconds": 2,
}

HOME_ASSISTANT_ENCRYPTED_FIELDS = ["token"]


def normalize_home_assistant_connection(raw: object) -> dict[str, object]:
    """Normalize a raw connection settings object into the expected shape."""
    base = deepcopy(DEFAULT_HOME_ASSISTANT_CONNECTION)
    if isinstance(raw, dict):
        base.update({k: v for k, v in raw.items() if k in base})
    return base


def mask_home_assistant_connection(raw: object) -> dict[str, object]:
    """Return a safe-for-API view of connection settings (redacts token)."""
    normalized = normalize_home_assistant_connection(raw)
    return mask_config(normalized, HOME_ASSISTANT_ENCRYPTED_FIELDS) or {}


def prepare_runtime_home_assistant_connection(raw: object) -> dict[str, object]:
    """Prepare connection settings for runtime use by decrypting the token."""
    return prepare_runtime_config(
        raw,
        encrypted_fields=HOME_ASSISTANT_ENCRYPTED_FIELDS,
        defaults=DEFAULT_HOME_ASSISTANT_CONNECTION,
    )
