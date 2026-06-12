"""
Rate limiting and failed-attempt lockout for alarm-code entry.

This is the single chokepoint shared by every path that submits an alarm PIN
(web disarm/arm, Ring Keypad v2, MQTT). It implements the same two-layer
defense login uses:

* **Rate limit** (``check_rate_limit``) — an ephemeral, per-source fixed-window
  counter in the Django cache. Mirrors login's DRF throttle; clearing on restart
  is correct for a rate limit. Limits come from the ``alarm_code.rate_limit_*``
  settings.
* **Lockout** (``is_locked_out`` / ``register_failed_attempt`` / ``reset_lockout``)
  — a durable, panel-wide block backed by the ``AlarmCodeLockout`` singleton row.
  Once ``alarm_code.lockout_threshold`` consecutive failures accumulate (across
  all sources), the whole panel is refused for ``alarm_code.lockout_duration_seconds``.
  DB-backed so it survives restarts and is shared across worker processes, exactly
  like ``User.locked_until`` — but global, because keypad/MQTT entries carry no
  user identity.

Both layers honor the ``0 = disabled`` convention (matching login's
``ACCOUNT_LOCKOUT_THRESHOLD=0``). This module intentionally never raises an
HTTP/domain exception: the lockout helpers return data and let each caller reject
in its own idiom (web raises, keypad flashes its indicator, MQTT publishes an error).

Imports are restricted to Django + ``alarm`` internals so that
``alarm/use_cases/alarm_actions.py`` can import it without breaking the
``alarm`` import boundary (no ``integrations_*`` / ``transports_*``).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from alarm.models import AlarmCodeLockout
from alarm.system_config_utils import get_int_system_config_value

logger = logging.getLogger(__name__)

_RATE_LIMIT_MAX_KEY = "alarm_code.rate_limit_max_attempts"
_RATE_LIMIT_WINDOW_KEY = "alarm_code.rate_limit_window_seconds"
_LOCKOUT_THRESHOLD_KEY = "alarm_code.lockout_threshold"
_LOCKOUT_DURATION_KEY = "alarm_code.lockout_duration_seconds"

_CACHE_PREFIX = "alarm_code_rl"


def check_rate_limit(source_key: str) -> bool:
    """
    Fixed-window rate limit for a single source.

    Returns ``True`` if the attempt is allowed, ``False`` if the source has
    exceeded ``alarm_code.rate_limit_max_attempts`` within
    ``alarm_code.rate_limit_window_seconds``. Disabled (always allows) when
    either setting is ``<= 0``. Fails **open** if the cache is unavailable, to
    match the existing keypad/MQTT limiters.
    """
    max_attempts = get_int_system_config_value(key=_RATE_LIMIT_MAX_KEY)
    window = get_int_system_config_value(key=_RATE_LIMIT_WINDOW_KEY)
    if max_attempts <= 0 or window <= 0:
        return True

    cache_key = f"{_CACHE_PREFIX}:{source_key}"
    try:
        cache.add(cache_key, 0, timeout=window)
        count = cache.incr(cache_key)
    except ValueError:
        # Key expired between add and incr — treat as the first hit of a fresh window.
        cache.set(cache_key, 1, timeout=window)
        count = 1
    except Exception:  # pragma: no cover - defensive: cache backend down
        logger.warning("Alarm-code rate-limit cache unavailable; allowing attempt", exc_info=True)
        return True

    return count <= max_attempts


def is_locked_out() -> tuple[bool, int]:
    """
    Report whether the panel is currently locked out for alarm-code entry.

    Returns ``(locked, seconds_remaining)``. Read-only — never creates the row.
    """
    row = AlarmCodeLockout.objects.filter(id=AlarmCodeLockout.SINGLETON_ID).first()
    if row is None or row.locked_until is None:
        return False, 0
    now = timezone.now()
    if row.locked_until <= now:
        return False, 0
    remaining = int((row.locked_until - now).total_seconds())
    return True, max(1, remaining)


def register_failed_attempt() -> None:
    """
    Record one failed alarm-code attempt against the global counter.

    When the running count reaches ``alarm_code.lockout_threshold`` the panel is
    locked for ``alarm_code.lockout_duration_seconds`` and the counter is reset
    (mirrors login's ``_register_failed_login``). No-op when lockout is disabled
    (``threshold <= 0``). The single row is locked with ``select_for_update`` so
    concurrent failures can't under-count.
    """
    threshold = get_int_system_config_value(key=_LOCKOUT_THRESHOLD_KEY)
    if threshold <= 0:
        return

    AlarmCodeLockout.objects.get_or_create(id=AlarmCodeLockout.SINGLETON_ID)
    with transaction.atomic():
        row = AlarmCodeLockout.objects.select_for_update().get(id=AlarmCodeLockout.SINGLETON_ID)
        row.failed_attempts += 1
        if row.failed_attempts >= threshold:
            duration = max(1, get_int_system_config_value(key=_LOCKOUT_DURATION_KEY))
            row.locked_until = timezone.now() + timedelta(seconds=duration)
            row.failed_attempts = 0
        row.save(update_fields=["failed_attempts", "locked_until", "updated_at"])


def reset_lockout() -> None:
    """
    Clear the failed-attempt counter and any active lockout after a valid code.

    Only writes when there is something to clear, to avoid churn on every
    successful arm/disarm.
    """
    (
        AlarmCodeLockout.objects.filter(id=AlarmCodeLockout.SINGLETON_ID)
        .exclude(failed_attempts=0, locked_until__isnull=True)
        .update(failed_attempts=0, locked_until=None)
    )
