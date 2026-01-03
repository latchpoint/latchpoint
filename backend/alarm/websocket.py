from __future__ import annotations

import itertools
import logging
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from alarm.serializers.alarm import AlarmStateSnapshotSerializer
from alarm.state_machine.timing import timing_from_snapshot

logger = logging.getLogger(__name__)

_sequence = itertools.count(1)


def build_alarm_state_message(*, snapshot) -> dict[str, Any]:
    """Build the websocket message envelope for an alarm snapshot + resolved timing."""
    timing = timing_from_snapshot(snapshot)
    return {
        "type": "alarm_state",
        "timestamp": timezone.now().isoformat(),
        "sequence": next(_sequence),
        "payload": {
            "state": AlarmStateSnapshotSerializer(snapshot).data,
            "effective_settings": timing.as_dict(),
        },
    }


def broadcast_alarm_state(*, snapshot) -> None:
    """Broadcast an alarm_state message to the Channels `alarm` group (best-effort)."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    message = build_alarm_state_message(snapshot=snapshot)
    async_to_sync(channel_layer.group_send)(
        "alarm",
        {
            "type": "broadcast",
            "message": message,
        },
    )


def build_entity_sync_message(*, entities: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the websocket message for entity state updates detected via sync."""
    return {
        "type": "entity_sync",
        "timestamp": timezone.now().isoformat(),
        "sequence": next(_sequence),
        "payload": {
            "entities": entities,
            "count": len(entities),
        },
    }


def broadcast_entity_sync(*, entities: list[dict[str, Any]]) -> None:
    """Broadcast entity state changes detected via sync to the Channels `alarm` group."""
    if not entities:
        return

    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.debug("No channel layer configured, skipping entity_sync broadcast")
        return

    message = build_entity_sync_message(entities=entities)
    try:
        async_to_sync(channel_layer.group_send)(
            "alarm",
            {
                "type": "broadcast",
                "message": message,
            },
        )
        logger.debug("Broadcast entity_sync: %d entities", len(entities))
    except Exception:
        logger.exception("Failed to broadcast entity_sync")
