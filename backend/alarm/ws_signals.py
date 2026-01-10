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
    try:
        from alarm.dispatcher import notify_entities_changed
        from alarm.dispatcher.entity_extractor import SYSTEM_ALARM_STATE_ENTITY_ID

        notify_entities_changed(
            source="alarm_state",
            entity_ids=[SYSTEM_ALARM_STATE_ENTITY_ID],
            changed_at=snapshot.entered_at,
        )
    except Exception:
        # Best-effort; alarm state WS broadcast is the primary side effect here.
        pass
