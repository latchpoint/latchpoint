from __future__ import annotations

from copy import deepcopy

from alarm.crypto import mask_config, prepare_runtime_config

DEFAULT_ZWAVEJS_CONNECTION: dict[str, object] = {
    "enabled": False,
    "ws_url": "ws://localhost:3000",
    "api_token": "",
    "connect_timeout_seconds": 5,
    "reconnect_min_seconds": 1,
    "reconnect_max_seconds": 30,
}

ZWAVEJS_ENCRYPTED_FIELDS = ["api_token"]


def normalize_zwavejs_connection(raw: object) -> dict[str, object]:
    """Normalize a raw connection settings object into the expected shape."""
    base = deepcopy(DEFAULT_ZWAVEJS_CONNECTION)
    if isinstance(raw, dict):
        base.update({k: v for k, v in raw.items() if k in base})
    return base


def mask_zwavejs_connection(raw: object) -> dict[str, object]:
    """Return a safe-for-API view of connection settings (redacts api_token)."""
    normalized = normalize_zwavejs_connection(raw)
    return mask_config(normalized, ZWAVEJS_ENCRYPTED_FIELDS) or {}


def prepare_runtime_zwavejs_connection(raw: object) -> dict[str, object]:
    """
    Returns a normalized connection dict with a decrypted `api_token` suitable for runtime usage.
    """
    return prepare_runtime_config(
        raw,
        encrypted_fields=ZWAVEJS_ENCRYPTED_FIELDS,
        defaults=DEFAULT_ZWAVEJS_CONNECTION,
    )
