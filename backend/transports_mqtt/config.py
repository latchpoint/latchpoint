from __future__ import annotations

from copy import deepcopy

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


def normalize_mqtt_connection(raw: object) -> dict[str, object]:
    """Normalize a raw connection settings object into the expected shape."""
    base = deepcopy(DEFAULT_MQTT_CONNECTION)
    if isinstance(raw, dict):
        base.update({k: v for k, v in raw.items() if k in base})
    return base
