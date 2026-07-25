"""Background tasks for the control_panels app."""

from __future__ import annotations

import logging

from alarm.models import AlarmState
from alarm.state_machine.transitions import get_current_snapshot
from control_panels.sync_worker import panel_sync_worker
from scheduler import Every, register

logger = logging.getLogger(__name__)

# Watchdog cadence. This is NOT what keeps the siren going — since ADR-0104 the tone has no
# device-side auto-stop and sounds until a mode indicator is selected — so the interval is not
# coupled to any tone duration and can be tuned freely.
_SIREN_RESYNC_INTERVAL_SECONDS = 120


@register(
    "resync_ring_keypad_siren",
    schedule=Every(seconds=_SIREN_RESYNC_INTERVAL_SECONDS),
    description="Watchdog that re-sounds the keypad siren if it stopped while still triggered (ADR-0104).",
)
def resync_ring_keypad_siren() -> dict:
    """
    Re-assert the Ring Keypad v2 burglar siren while the alarm is triggered.

    Since ADR-0104 the siren sounds continuously until a disarm/arm selects a mode indicator, so
    this task is no longer load-bearing for continuity — it is pure recovery. It repairs the
    cases the state-change sync cannot see: the initial activation write failed, an external
    HA/zwave-js write silenced the tone, or the keypad rebooted mid-alarm.

    There is deliberately no bell cutoff. ADR-0098 added one that worked by declining to
    re-assert and letting the device's 240 s timeout expire; with no auto-stop left, declining to
    re-assert would not silence anything, and the alarm is required to sound until disarmed.
    Re-asserting writes 0 over 0, which is hardware-verified to sound the siren.
    """
    snapshot = get_current_snapshot(process_timers=False)
    if snapshot is None or snapshot.current_state != AlarmState.TRIGGERED:
        return {"resynced": False, "reason": "not_triggered"}

    logger.info("Ring Keypad v2 siren re-assert: alarm still triggered")
    panel_sync_worker.request_siren_reassert()
    return {"resynced": True}
