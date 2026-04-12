from __future__ import annotations

from copy import deepcopy

DEFAULT_HOME_ASSISTANT_CONNECTION: dict[str, object] = {
    "enabled": False,
    "base_url": "http://localhost:8123",
    "token": "",
    "connect_timeout_seconds": 2,
    "request_timeout_seconds": 5,
}


def normalize_home_assistant_connection(raw: object) -> dict[str, object]:
    """Normalize a raw connection settings object into the expected shape."""
    base = deepcopy(DEFAULT_HOME_ASSISTANT_CONNECTION)
    if isinstance(raw, dict):
        base.update({k: v for k, v in raw.items() if k in base})
    return base
