from __future__ import annotations

from copy import deepcopy

from alarm.crypto import mask_config, prepare_runtime_config

DEFAULT_MQTT_CONNECTION: dict[str, object] = {
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
}

MQTT_ENCRYPTED_FIELDS = ["password"]


def normalize_mqtt_connection(raw: object) -> dict[str, object]:
    """Normalize a raw connection settings object into the expected shape."""
    base = deepcopy(DEFAULT_MQTT_CONNECTION)
    if isinstance(raw, dict):
        base.update({k: v for k, v in raw.items() if k in base})
    return base


def mask_mqtt_connection(raw: object) -> dict[str, object]:
    """Return a safe-for-API view of connection settings (redacts password)."""
    normalized = normalize_mqtt_connection(raw)
    return mask_config(normalized, MQTT_ENCRYPTED_FIELDS) or {}


def prepare_runtime_mqtt_connection(raw: object) -> dict[str, object]:
    """
    Returns a normalized connection dict with a decrypted `password` suitable for runtime usage.
    """
    return prepare_runtime_config(
        raw,
        encrypted_fields=MQTT_ENCRYPTED_FIELDS,
        defaults=DEFAULT_MQTT_CONNECTION,
    )
