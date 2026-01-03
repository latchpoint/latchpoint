from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.cache import cache
from django.utils import timezone


_PREFIX = "zigbee2mqtt:"
_CACHE_LAST_SEEN_AT = f"{_PREFIX}last_seen_at"
_CACHE_LAST_STATE = f"{_PREFIX}last_state"


@dataclass(frozen=True)
class Zigbee2mqttLastSync:
    last_sync_at: str | None
    last_device_count: int | None
    last_error: str | None

    def as_dict(self) -> dict[str, Any]:
        """Serialize last sync status to a JSON-friendly dict for API responses."""
        return {
            "last_sync_at": self.last_sync_at,
            "last_device_count": self.last_device_count,
            "last_error": self.last_error,
        }


def mark_sync(*, device_count: int) -> None:
    """Record a successful sync run (best-effort)."""
    cache.set(f"{_PREFIX}last_sync_at", timezone.now().isoformat(), timeout=None)
    cache.set(f"{_PREFIX}last_device_count", int(device_count), timeout=None)
    cache.set(f"{_PREFIX}last_error", None, timeout=None)


def mark_error(*, error: str) -> None:
    """Record a sync error (best-effort)."""
    cache.set(f"{_PREFIX}last_error", str(error), timeout=None)


def mark_seen(*, state: str | None = None) -> None:
    """Record that Zigbee2MQTT was seen recently, optionally capturing bridge state."""
    cache.set(_CACHE_LAST_SEEN_AT, timezone.now().isoformat(), timeout=None)
    if state is not None:
        cache.set(_CACHE_LAST_STATE, str(state), timeout=None)


def get_last_seen_at() -> str | None:
    """Return the last-seen timestamp string, if known."""
    val = cache.get(_CACHE_LAST_SEEN_AT)
    return val if isinstance(val, str) else None


def get_last_state() -> str | None:
    """Return the last known Zigbee2MQTT bridge state string, if known."""
    val = cache.get(_CACHE_LAST_STATE)
    return val if isinstance(val, str) else None


def get_last_sync() -> Zigbee2mqttLastSync:
    """Return the last device sync status payload."""
    return Zigbee2mqttLastSync(
        last_sync_at=cache.get(f"{_PREFIX}last_sync_at"),
        last_device_count=cache.get(f"{_PREFIX}last_device_count"),
        last_error=cache.get(f"{_PREFIX}last_error"),
    )
