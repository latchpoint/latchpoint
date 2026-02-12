from __future__ import annotations

import logging
import threading
from datetime import timedelta

from django.dispatch import receiver
from django.utils import timezone

from alarm.models import AlarmEvent, AlarmEventType
from alarm.signals import integration_status_changed, integration_status_observed

logger = logging.getLogger(__name__)

_OUTAGE_THRESHOLD_SECONDS = 60


class IntegrationOutageTracker:
    """Thread-safe tracker for integration offline state and event deduplication."""

    def __init__(self):
        self._lock = threading.Lock()
        self._offline_since: dict[str, timezone.datetime] = {}
        self._event_emitted: set[str] = set()

    def mark_offline(self, integration: str, now) -> None:
        with self._lock:
            self._offline_since[integration] = now
            self._event_emitted.discard(integration)

    def mark_online(self, integration: str) -> timezone.datetime | None:
        with self._lock:
            start = self._offline_since.pop(integration, None)
            self._event_emitted.discard(integration)
        return start

    def get_offline_start(self, integration: str):
        with self._lock:
            return self._offline_since.get(integration)

    def is_event_emitted(self, integration: str) -> bool:
        with self._lock:
            return integration in self._event_emitted

    def set_event_emitted(self, integration: str) -> None:
        with self._lock:
            self._event_emitted.add(integration)

    def record_initial_offline(self, integration: str, now) -> None:
        self.mark_offline(integration, now)


_tracker = IntegrationOutageTracker()


@receiver(integration_status_changed)
def log_integration_transition(sender, *, integration: str, is_healthy: bool, previous_healthy: bool | None, **kwargs) -> None:
    """Persist significant integration state transitions as AlarmEvents."""
    now = timezone.now()

    if previous_healthy is None:
        if not is_healthy:
            _tracker.record_initial_offline(integration, now)
        return

    if previous_healthy and not is_healthy:
        _tracker.mark_offline(integration, now)
        logger.warning("Integration %s went offline", integration)
        return

    if not previous_healthy and is_healthy:
        offline_start = _tracker.mark_online(integration)
        offline_duration = (now - (offline_start or now)).total_seconds()
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


@receiver(integration_status_observed)
def log_prolonged_outage(sender, *, integration: str, is_healthy: bool, checked_at: timezone.datetime, **kwargs) -> None:
    """Create outage event once an integration is offline for the threshold duration."""
    if is_healthy:
        return

    offline_start = _tracker.get_offline_start(integration)
    if not offline_start:
        return

    offline_duration = (checked_at - offline_start).total_seconds()
    if offline_duration < _OUTAGE_THRESHOLD_SECONDS:
        return

    if _tracker.is_event_emitted(integration):
        return

    now = timezone.now()
    recent_event = AlarmEvent.objects.filter(
        event_type=AlarmEventType.INTEGRATION_OFFLINE,
        timestamp__gte=now - timedelta(minutes=5),
        metadata__integration=integration,
    ).exists()
    if recent_event:
        _tracker.set_event_emitted(integration)
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
    _tracker.set_event_emitted(integration)
