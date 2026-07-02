"""Background tasks for the control_panels app."""

from __future__ import annotations

import logging

from django.utils import timezone

from alarm.models import AlarmEvent, AlarmEventType, AlarmState
from alarm.state_machine.transitions import get_current_snapshot
from control_panels.zwave_ring_keypad_v2 import (
    _BURGLAR_SIREN_MAX_TOTAL_SECONDS,
    sync_ring_keypad_v2_devices_state,
)
from scheduler import Every, register

logger = logging.getLogger(__name__)

# Must stay below _BURGLAR_SIREN_SECONDS (240) so each re-send lands while the
# previous tone is still playing and the siren sounds continuously.
_SIREN_RESYNC_INTERVAL_SECONDS = 120


@register(
    "resync_ring_keypad_siren",
    schedule=Every(seconds=_SIREN_RESYNC_INTERVAL_SECONDS),
    description="Keeps the keypad siren sounding while the alarm stays triggered (ADR-0098).",
)
def resync_ring_keypad_siren() -> dict:
    """
    Re-assert the Ring Keypad v2 burglar siren while the alarm is triggered.

    The Indicator CC tone is one-shot with a 255 s ceiling and the keypad only
    re-syncs on alarm state changes (ADR-0097), so a long `triggered` state goes
    silent after ~4 minutes. This task re-sends the siren command until the
    bell cutoff (`_BURGLAR_SIREN_MAX_TOTAL_SECONDS`) elapses; leaving the
    triggered state silences the keypad via the normal state-change sync.
    """
    snapshot = get_current_snapshot(process_timers=False)
    if snapshot is None or snapshot.current_state != AlarmState.TRIGGERED:
        return {"resynced": False, "reason": "not_triggered"}

    triggered_event = AlarmEvent.objects.filter(event_type=AlarmEventType.TRIGGERED).order_by("-timestamp").first()
    if triggered_event is not None:
        elapsed_seconds = (timezone.now() - triggered_event.timestamp).total_seconds()
        if elapsed_seconds > _BURGLAR_SIREN_MAX_TOTAL_SECONDS:
            return {"resynced": False, "reason": "bell_cutoff", "elapsed_seconds": int(elapsed_seconds)}

    logger.info("Ring Keypad v2 siren re-assert: alarm still triggered")
    sync_ring_keypad_v2_devices_state()
    return {"resynced": True}
