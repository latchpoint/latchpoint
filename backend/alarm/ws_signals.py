from __future__ import annotations

import logging

from django.dispatch import receiver

from alarm.models import AlarmStateSnapshot
from alarm.signals import alarm_state_change_committed
from alarm.websocket import broadcast_alarm_state

logger = logging.getLogger(__name__)


@receiver(alarm_state_change_committed)
def _on_alarm_state_change_committed(sender, *, state_to: str, **kwargs) -> None:
    """Broadcast alarm state to websocket listeners after committed state changes."""
    snapshot = AlarmStateSnapshot.objects.select_related("settings_profile").first()
    if not snapshot:
        logger.warning("WS alarm_state_change_committed: no snapshot found (state_to=%s)", state_to)
        return
    broadcast_alarm_state(snapshot=snapshot)
