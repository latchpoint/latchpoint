"""Signal receivers for the notifications app."""

from __future__ import annotations

import logging

from django.dispatch import receiver
from django.utils import timezone

from alarm.models import AlarmState
from alarm.signals import alarm_state_change_committed

logger = logging.getLogger(__name__)


@receiver(alarm_state_change_committed, dispatch_uid="notifications_alarm_triggered")
def notify_on_alarm_triggered(sender, *, state_to: str, **kwargs) -> None:
    """
    Enqueue a notification to every enabled provider when the alarm turns triggered.

    Fires on the state transition itself (ADR-0098), so it works regardless of rule
    configuration — a `send_notification` rule action would fire at entry-delay start
    instead of at the actual trigger. Deliveries go through the durable outbox and are
    drained by the `notifications_send_pending` task.
    """
    if state_to != AlarmState.TRIGGERED:
        return

    # Imported lazily: this module loads at app-ready, before sibling apps finish wiring.
    from alarm.state_machine.settings import get_active_settings_profile
    from notifications.dispatcher import get_dispatcher
    from notifications.models import NotificationProvider

    try:
        profile = get_active_settings_profile()
        providers = list(NotificationProvider.objects.filter(profile=profile, is_enabled=True))
        if not providers:
            logger.warning("Alarm triggered but no enabled notification providers are configured.")
            return

        dispatcher = get_dispatcher()
        message = f"Alarm TRIGGERED at {timezone.localtime():%Y-%m-%d %H:%M:%S}."
        for provider in providers:
            delivery, result = dispatcher.enqueue(
                profile=profile,
                provider_id=str(provider.id),
                message=message,
                title="Alarm triggered",
            )
            if delivery is None:
                logger.warning(
                    "Failed to enqueue alarm-triggered notification for provider %s: %s",
                    provider.name,
                    result.message,
                )
    except Exception:
        logger.exception("Failed to enqueue alarm-triggered notifications")
