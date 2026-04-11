from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from threading import Lock

from django.conf import settings


@dataclass(frozen=True)
class HomeAssistantRuntimeConnection:
    enabled: bool
    base_url: str
    token: str
    connect_timeout_seconds: float
    error: str | None = None


_lock = Lock()
_cached: HomeAssistantRuntimeConnection | None = None
_warmup_lock = Lock()
_last_warmup_attempt_at: float = 0.0


def _home_assistant_allowed_in_tests() -> bool:
    """Return True if Home Assistant integration I/O is allowed in the current test run."""
    if "test" not in sys.argv:
        return True
    return bool(getattr(settings, "ALLOW_HOME_ASSISTANT_IN_TESTS", False))


def get_cached_connection() -> HomeAssistantRuntimeConnection | None:
    """Return the in-process cached Home Assistant runtime connection (if any)."""
    with _lock:
        return _cached


def clear_cached_connection() -> None:
    """
    Clear the in-process runtime cache.

    Primarily intended for tests; safe to call in production.
    """

    with _lock:
        global _cached
        _cached = None

    with _warmup_lock:
        global _last_warmup_attempt_at
        _last_warmup_attempt_at = 0.0


def set_cached_connection() -> None:
    """
    Cache the Home Assistant connection settings from DB (ADR 0079).

    This must not raise; callers treat caching as best-effort.
    """
    from integrations_home_assistant.views import get_ha_settings

    try:
        cfg = get_ha_settings()
    except Exception:
        return

    defaults = {"enabled": False, "base_url": "", "token": "", "connect_timeout_seconds": 2}
    try:
        obj = HomeAssistantRuntimeConnection(
            enabled=bool(cfg.get("enabled", defaults["enabled"])),
            base_url=str(cfg.get("base_url") or defaults["base_url"]),
            token=str(cfg.get("token") or defaults["token"]),
            connect_timeout_seconds=float(cfg.get("connect_timeout_seconds") or defaults["connect_timeout_seconds"]),
        )
    except (TypeError, ValueError):
        obj = HomeAssistantRuntimeConnection(**defaults)

    with _lock:
        global _cached
        _cached = obj


def warm_up_cached_connection_if_needed(*, min_interval_seconds: float = 2.0) -> None:
    """
    Best-effort warm-up of the in-process runtime cache from env vars.

    Debounces repeated calls within *min_interval_seconds*.
    """

    if get_cached_connection() is not None:
        return
    if not _home_assistant_allowed_in_tests():
        return

    now = time.monotonic()
    with _warmup_lock:
        if get_cached_connection() is not None:
            return
        global _last_warmup_attempt_at
        if now - _last_warmup_attempt_at < float(min_interval_seconds or 0.0):
            return
        _last_warmup_attempt_at = now

    try:
        set_cached_connection()
    except Exception:
        return
