"""
Post-disarm re-arm guard.

Stops an accidental or duplicate *arm* command from silently re-arming the panel
in the brief window right after a disarm.

Motivating incident: while the panel was ``pending`` a user repeatedly pressed
Disarm on the Home Assistant alarm-panel card. The card swaps its Disarm button
for Arm buttons the instant the state flips to ``disarmed``, so one rapid tap
landed on *Arm Away* (with the PIN still in the field) and re-armed the panel —
which made it look like disarming "wasn't working". Mashing Disarm is legitimate
user behavior and must never arm the panel.

Design: a single cache-backed marker shared by every disarm. ``mark_disarmed``
is called from the state machine's ``disarm`` (on commit), so every disarm — from
any source — opens the window. The human command paths (MQTT, Ring Keypad v2)
consult ``recently_disarmed`` before arming and refuse while the window is
active. Programmatic arms (rules engine, scheduler) intentionally do NOT consult
it, so automations are never blocked.

The window comes from the ``alarm.rearm_guard_seconds`` system setting (``0``
disables the guard). Both helpers fail **open** (behave as "not recently
disarmed") if the cache backend is unavailable, matching the keypad/MQTT rate
limiters — degrading to today's behavior rather than blocking the panel.

Imports stay within Django + ``alarm`` internals so integration/control-panel
callers can import it without tripping the ``alarm`` import boundary.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.utils import timezone

from alarm.system_config_utils import get_int_system_config_value

logger = logging.getLogger(__name__)

_WINDOW_KEY = "alarm.rearm_guard_seconds"
_CACHE_KEY = "alarm_rearm_guard:last_disarm"


def _window_seconds() -> int:
    return get_int_system_config_value(key=_WINDOW_KEY)


def mark_disarmed() -> None:
    """Open the re-arm guard window: record that a disarm just happened.

    No-op when the guard is disabled (``alarm.rearm_guard_seconds <= 0``).
    Best-effort — a missing/broken cache backend is logged and ignored.
    """
    window = _window_seconds()
    if window <= 0:
        return
    try:
        cache.set(_CACHE_KEY, timezone.now().timestamp(), timeout=window)
    except Exception:  # pragma: no cover - defensive: cache backend down
        logger.warning("Re-arm guard cache unavailable; disarm not marked", exc_info=True)


def recently_disarmed() -> tuple[bool, int]:
    """Report whether a disarm happened within the guard window.

    Returns ``(blocked, seconds_remaining)``. ``blocked`` is ``True`` while an
    arm should be refused; ``seconds_remaining`` (>= 1) feeds the user-facing
    "try again in Ns" message. Disabled guard or unavailable cache both yield
    ``(False, 0)`` (fail open).
    """
    window = _window_seconds()
    if window <= 0:
        return False, 0
    try:
        marked_at = cache.get(_CACHE_KEY)
    except Exception:  # pragma: no cover - defensive: cache backend down
        logger.warning("Re-arm guard cache unavailable; allowing arm", exc_info=True)
        return False, 0
    if marked_at is None:
        return False, 0
    remaining = int(window - (timezone.now().timestamp() - float(marked_at)))
    if remaining <= 0:
        return False, 0
    return True, max(1, remaining)
