from __future__ import annotations

from copy import deepcopy

DEFAULT_ZWAVEJS_CONNECTION: dict[str, object] = {
    "enabled": False,
    "ws_url": "ws://localhost:3000",
    "api_token": "",
    "connect_timeout_seconds": 5,
    "reconnect_min_seconds": 1,
    "reconnect_max_seconds": 30,
    "request_timeout_seconds": 10,
}


def normalize_zwavejs_connection(raw: object) -> dict[str, object]:
    """Normalize a raw connection settings object into the expected shape."""
    base = deepcopy(DEFAULT_ZWAVEJS_CONNECTION)
    if isinstance(raw, dict):
        base.update({k: v for k, v in raw.items() if k in base})
    return base
