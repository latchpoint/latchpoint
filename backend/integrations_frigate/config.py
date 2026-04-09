from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FrigateSettings:
    enabled: bool
    events_topic: str
    retention_seconds: int


DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "events_topic": "frigate/events",
    "retention_seconds": 3600,
}


def normalize_frigate_settings(raw: object) -> FrigateSettings:
    """Normalize a raw settings dict into a typed `FrigateSettings`."""
    data = raw if isinstance(raw, dict) else {}
    enabled = bool(data.get("enabled", False))

    events_topic = str(data.get("events_topic") or DEFAULT_SETTINGS["events_topic"]).strip()
    if not events_topic:
        events_topic = str(DEFAULT_SETTINGS["events_topic"])

    retention_seconds_raw = data.get("retention_seconds", DEFAULT_SETTINGS["retention_seconds"])
    try:
        retention_seconds = int(retention_seconds_raw)
    except Exception:
        retention_seconds = int(DEFAULT_SETTINGS["retention_seconds"])
    if retention_seconds <= 0:
        retention_seconds = int(DEFAULT_SETTINGS["retention_seconds"])

    return FrigateSettings(
        enabled=enabled,
        events_topic=events_topic,
        retention_seconds=retention_seconds,
    )
