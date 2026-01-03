from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from threading import Lock

from django.conf import settings

from alarm.crypto import EncryptionNotConfigured
from integrations_home_assistant.config import (
    normalize_home_assistant_connection,
    prepare_runtime_home_assistant_connection,
)


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


def set_cached_connection(raw: object) -> None:
    """
    Cache the (decrypted) Home Assistant connection settings for request-time usage.

    This must not raise; callers treat caching as best-effort.
    """

    normalized = normalize_home_assistant_connection(raw)
    try:
        runtime = prepare_runtime_home_assistant_connection(normalized)
        error = None
    except EncryptionNotConfigured as exc:
        runtime = dict(normalized)
        runtime["token"] = ""
        error = str(exc)

    obj = HomeAssistantRuntimeConnection(
        enabled=bool(runtime.get("enabled")),
        base_url=str(runtime.get("base_url") or ""),
        token=str(runtime.get("token") or ""),
        connect_timeout_seconds=float(runtime.get("connect_timeout_seconds") or 2),
        error=error,
    )
    with _lock:
        global _cached
        _cached = obj


def warm_up_cached_connection_if_needed(*, min_interval_seconds: float = 2.0) -> None:
    """
    Best-effort warm-up of the in-process runtime cache from the active profile.

    This is useful when app startup warms the cache before the DB is ready; in that
    case `ready()`'s warm-up fails silently and the first request sees an empty cache.
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
        apply_from_active_profile_if_exists()
    except Exception:
        return


def apply_from_profile_id(*, profile_id: int) -> None:
    """
    Best-effort load of the HA connection settings from the DB, without creating profiles.
    """

    if not _home_assistant_allowed_in_tests():
        return

    try:
        from alarm.models import AlarmSettingsEntry
    except Exception:
        return

    try:
        entry = (
            AlarmSettingsEntry.objects.filter(profile_id=profile_id, key="home_assistant_connection")
            .only("value")
            .first()
        )
    except Exception:
        return

    if not entry:
        return
    set_cached_connection(entry.value)


def apply_from_active_profile_if_exists() -> None:
    """
    Best-effort cache warm-up on startup.
    """

    if not _home_assistant_allowed_in_tests():
        return

    try:
        from alarm.models import AlarmSettingsProfile
    except Exception:
        return

    try:
        profile = AlarmSettingsProfile.objects.filter(is_active=True).only("id").first()
    except Exception:
        return

    if not profile:
        return
    apply_from_profile_id(profile_id=int(profile.id))
