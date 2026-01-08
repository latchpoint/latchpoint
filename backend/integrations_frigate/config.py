from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _as_dict(value: object) -> dict[str, Any]:
    """Coerce a value into a dict, returning {} for non-dicts."""
    if isinstance(value, dict):
        return value
    return {}


@dataclass(frozen=True)
class FrigateSettings:
    enabled: bool
    events_topic: str
    retention_seconds: int
    known_cameras: list[str]
    known_zones_by_camera: dict[str, list[str]]


DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "events_topic": "frigate/events",
    "retention_seconds": 3600,
    "known_cameras": [],
    "known_zones_by_camera": {},
}


def normalize_frigate_settings(raw: object) -> FrigateSettings:
    """Normalize a raw JSON settings object into a typed `FrigateSettings`."""
    data = _as_dict(raw)
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

    known_cameras_raw = data.get("known_cameras", DEFAULT_SETTINGS["known_cameras"])
    known_cameras: list[str] = []
    if isinstance(known_cameras_raw, list):
        known_cameras = [str(c).strip() for c in known_cameras_raw if isinstance(c, str) and str(c).strip()]

    known_zones_by_camera_raw = data.get("known_zones_by_camera", DEFAULT_SETTINGS["known_zones_by_camera"])
    known_zones_by_camera: dict[str, list[str]] = {}
    if isinstance(known_zones_by_camera_raw, dict):
        for cam, zones_raw in known_zones_by_camera_raw.items():
            if not isinstance(cam, str) or not cam.strip():
                continue
            zones: list[str] = []
            if isinstance(zones_raw, list):
                zones = [str(z).strip() for z in zones_raw if isinstance(z, str) and str(z).strip()]
            if zones:
                known_zones_by_camera[cam.strip()] = zones

    return FrigateSettings(
        enabled=enabled,
        events_topic=events_topic,
        retention_seconds=retention_seconds,
        known_cameras=known_cameras,
        known_zones_by_camera=known_zones_by_camera,
    )
