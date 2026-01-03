from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils import timezone


def normalize_confidence_pct(value: object) -> float | None:
    """
    Accepts either:
    - fraction [0, 1] (common in Frigate payloads)
    - percent [0, 100]
    Returns a float percent in [0, 100] or None if invalid.
    """
    if value is None:
        return None
    try:
        c = float(value)
    except Exception:
        return None
    if c != c:  # NaN
        return None
    if 0.0 <= c <= 1.0:
        return max(0.0, min(100.0, c * 100.0))
    if 0.0 <= c <= 100.0:
        return max(0.0, min(100.0, c))
    return max(0.0, min(100.0, c))


def _coerce_dt_from_epoch_seconds(value: object) -> datetime | None:
    """Coerce epoch seconds into a timezone-aware datetime, returning None when invalid."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except Exception:
        return None
    if seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except Exception:
        return None


@dataclass(frozen=True)
class ParsedDetection:
    provider: str
    event_id: str
    label: str
    camera: str
    zones: list[str]
    confidence_pct: float
    observed_at: datetime
    raw: dict[str, Any]


def parse_frigate_events_payload(payload_obj: object) -> ParsedDetection | None:
    """
    Parses the common Frigate MQTT topic `frigate/events` message shape.

    Typical shape (varies by version/config):
    {
      "type": "new"|"update"|"end",
      "before": {...},
      "after": {
        "id": "...",
        "camera": "backyard",
        "label": "person",
        "top_score": 0.92,
        "entered_zones": ["backyard"],
        "start_time": 1730000000.0,
        "end_time": 1730000005.0,
        ...
      }
    }
    """
    if not isinstance(payload_obj, dict):
        return None

    # Common `frigate/events` wrapper includes `after`.
    after = payload_obj.get("after")
    if not isinstance(after, dict):
        # Some installations publish the event payload directly.
        after = payload_obj

    label = str(after.get("label") or "").strip()
    camera = str(after.get("camera") or "").strip()
    if not label or not camera:
        return None

    event_id = str(after.get("id") or payload_obj.get("id") or "").strip()

    raw_zones = after.get("entered_zones")
    if raw_zones is None:
        raw_zones = after.get("current_zones")
    zones: list[str] = []
    if isinstance(raw_zones, list):
        zones = [str(z).strip() for z in raw_zones if isinstance(z, str) and z.strip()]

    score = after.get("top_score")
    if score is None:
        score = after.get("score")
    if score is None:
        score = after.get("confidence")
    confidence_pct = normalize_confidence_pct(score)
    if confidence_pct is None:
        return None

    observed_at = (
        _coerce_dt_from_epoch_seconds(after.get("end_time"))
        or _coerce_dt_from_epoch_seconds(after.get("start_time"))
        or timezone.now()
    )

    return ParsedDetection(
        provider="frigate",
        event_id=event_id,
        label=label,
        camera=camera,
        zones=zones,
        confidence_pct=confidence_pct,
        observed_at=observed_at,
        raw=payload_obj,
    )
