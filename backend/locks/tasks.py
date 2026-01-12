"""Background tasks for the locks app."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from alarm.system_config_utils import get_int_system_config_value
from scheduler import DailyAt, register

from .models import DoorCodeEvent

logger = logging.getLogger(__name__)


def _get_door_code_event_retention_days() -> int:
    """Read door_code_events.retention_days from SystemConfig, fallback to default."""
    return get_int_system_config_value(key="door_code_events.retention_days")


@register(
    "cleanup_door_code_events",
    schedule=DailyAt(hour=3, minute=10),
    description="Deletes old door code audit events based on your retention settings.",
)
def cleanup_door_code_events() -> int:
    """
    Delete DoorCodeEvent records older than the configured retention period.

    Returns the count of deleted records.
    """
    retention_days = _get_door_code_event_retention_days()
    if retention_days <= 0:
        return 0

    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted_count, _ = DoorCodeEvent.objects.filter(created_at__lt=cutoff).delete()

    if deleted_count > 0:
        logger.info(
            "Cleaned up %d door code events older than %d days (cutoff: %s)",
            deleted_count,
            retention_days,
            cutoff.isoformat(),
        )

    return deleted_count
