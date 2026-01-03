from __future__ import annotations

import logging
from datetime import timedelta

from django.dispatch import receiver
from django.utils import timezone

from alarm.models import AlarmEvent, AlarmEventType
from alarm.signals import integration_status_changed, integration_status_observed

logger = logging.getLogger(__name__)

_OUTAGE_THRESHOLD_SECONDS = 60

_offline_since: dict[str, timezone.datetime] = {}
_offline_event_emitted: set[str] = set()


@receiver(integration_status_changed)
def log_integration_transition(sender, *, integration: str, is_healthy: bool, previous_healthy: bool | None, **kwargs) -> None:
    """Persist significant integration state transitions as AlarmEvents."""
    now = timezone.now()

    if previous_healthy is None:
        if not is_healthy:
            _offline_since[integration] = now
        return

    if previous_healthy and not is_healthy:
        _offline_since[integration] = now
        _offline_event_emitted.discard(integration)
        logger.warning("Integration %s went offline", integration)
        return

    if not previous_healthy and is_healthy:
        offline_duration = (now - _offline_since.get(integration, now)).total_seconds()
        logger.info("Integration %s back online after %.0fs", integration, offline_duration)

        if offline_duration >= _OUTAGE_THRESHOLD_SECONDS:
            AlarmEvent.objects.create(
                event_type=AlarmEventType.INTEGRATION_RECOVERED,
                timestamp=now,
                metadata={
                    "integration": integration,
                    "offline_duration_seconds": offline_duration,
                },
            )

        _offline_since.pop(integration, None)
        _offline_event_emitted.discard(integration)


@receiver(integration_status_observed)
def log_prolonged_outage(sender, *, integration: str, is_healthy: bool, checked_at: timezone.datetime, **kwargs) -> None:
    """Create outage event once an integration is offline for the threshold duration."""
    if is_healthy:
        return

    offline_start = _offline_since.get(integration)
    if not offline_start:
        return

    offline_duration = (checked_at - offline_start).total_seconds()
    if offline_duration < _OUTAGE_THRESHOLD_SECONDS:
        return

    if integration in _offline_event_emitted:
        return

    now = timezone.now()
    recent_event = AlarmEvent.objects.filter(
        event_type=AlarmEventType.INTEGRATION_OFFLINE,
        timestamp__gte=now - timedelta(minutes=5),
        metadata__integration=integration,
    ).exists()
    if recent_event:
        _offline_event_emitted.add(integration)
        return

    logger.error("Integration %s offline for %.0fs", integration, offline_duration)
    AlarmEvent.objects.create(
        event_type=AlarmEventType.INTEGRATION_OFFLINE,
        timestamp=now,
        metadata={
            "integration": integration,
            "offline_duration_seconds": offline_duration,
        },
    )
    _offline_event_emitted.add(integration)

