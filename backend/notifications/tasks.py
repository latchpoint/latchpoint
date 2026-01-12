"""Background tasks for notifications."""

from __future__ import annotations

import logging
import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from alarm.system_config_utils import get_int_system_config_value
from scheduler import DailyAt, Every, register

from .dispatcher import get_dispatcher
from .models import NotificationDelivery, NotificationLog

logger = logging.getLogger(__name__)


_NO_RETRY_ERROR_CODES = {
    "AUTH_FAILED",
    "FORBIDDEN",
    "INVALID_CONFIG",
    "INVALID_SERVICE",
    "MISSING_SERVICE",
    "PROVIDER_DISABLED",
    "PROVIDER_NOT_FOUND",
    "UNKNOWN_PROVIDER_TYPE",
}

_RETRY_ERROR_CODES = {
    "TIMEOUT",
    "NETWORK_ERROR",
    "SERVER_ERROR",
    "RATE_LIMITED",
    "HA_NOT_REACHABLE",
    "HA_ERROR",
}


def _should_retry(*, error_code: str | None) -> bool:
    if not error_code:
        return True
    if error_code in _NO_RETRY_ERROR_CODES:
        return False
    if error_code in _RETRY_ERROR_CODES:
        return True
    # Default: retry unknown failures a limited number of times
    return True


def _compute_backoff_seconds(*, attempt: int, error_code: str | None) -> int:
    """
    Compute backoff (seconds) for the next retry attempt.

    `attempt` is 1-based (first failure => attempt=1).
    """
    attempt = max(1, attempt)
    base = 5
    if error_code == "RATE_LIMITED":
        base = 30
    seconds = base * (2 ** (attempt - 1))
    seconds = min(seconds, 600)  # cap at 10 minutes
    jitter = int(random.uniform(0, 1) * 2)  # 0-1s
    return seconds + jitter


@register(
    "notifications_send_pending",
    schedule=Every(seconds=5, jitter=1),
    description="Sends pending notifications and retries temporary failures.",
)
def notifications_send_pending() -> int:
    """
    Process due NotificationDelivery rows.

    Returns number of deliveries marked as sent.
    """
    now = timezone.now()
    sent_count = 0

    # Reclaim stale "sending" rows (e.g., process crash mid-send)
    from django.conf import settings

    lock_timeout_seconds = getattr(settings, "NOTIFICATIONS_DELIVERY_LOCK_TIMEOUT_SECONDS", 60)
    stale_before = now - timedelta(seconds=int(lock_timeout_seconds))
    reclaimed = NotificationDelivery.objects.filter(
        status=NotificationDelivery.Status.SENDING,
        locked_at__lt=stale_before,
    ).update(
        status=NotificationDelivery.Status.PENDING,
        locked_at=None,
    )
    if reclaimed:
        logger.warning("Reclaimed %d stale notification deliveries", reclaimed)

    while True:
        with transaction.atomic():
            batch = list(
                NotificationDelivery.objects.select_for_update(skip_locked=True)
                .filter(
                    status=NotificationDelivery.Status.PENDING,
                    next_attempt_at__lte=now,
                )
                .order_by("next_attempt_at", "created_at")[:10]
            )
            if not batch:
                break

            NotificationDelivery.objects.filter(id__in=[d.id for d in batch]).update(
                status=NotificationDelivery.Status.SENDING,
                locked_at=now,
            )

        dispatcher = get_dispatcher()

        for delivery in batch:
            attempt_started_at = timezone.now()
            try:
                result = dispatcher._send_now(
                    provider_id=delivery.provider_key,
                    message=delivery.message,
                    title=delivery.title or None,
                    data=delivery.data or None,
                    rule_name=delivery.rule_name,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Unexpected error sending notification delivery %s", delivery.id)
                result = None
                error_message = str(exc)
                error_code = "UNKNOWN_ERROR"
            else:
                error_message = result.message if result else "Unknown error"
                error_code = (result.error_code if result else None) or ""

            delivery.attempt_count += 1
            delivery.last_attempt_at = attempt_started_at
            delivery.locked_at = None

            if result and result.success:
                delivery.status = NotificationDelivery.Status.SENT
                delivery.sent_at = timezone.now()
                delivery.last_error_code = ""
                delivery.last_error_message = ""
                delivery.next_attempt_at = timezone.now()
                delivery.save(
                    update_fields=[
                        "attempt_count",
                        "status",
                        "sent_at",
                        "last_attempt_at",
                        "locked_at",
                        "last_error_code",
                        "last_error_message",
                        "next_attempt_at",
                        "updated_at",
                    ]
                )
                sent_count += 1
                continue

            delivery.last_error_code = error_code
            delivery.last_error_message = error_message

            if _should_retry(error_code=error_code) and delivery.attempt_count < delivery.max_attempts:
                delay_seconds = _compute_backoff_seconds(
                    attempt=delivery.attempt_count,
                    error_code=error_code,
                )
                delivery.status = NotificationDelivery.Status.PENDING
                delivery.next_attempt_at = timezone.now() + timedelta(seconds=delay_seconds)
            else:
                delivery.status = NotificationDelivery.Status.DEAD

            delivery.save(
                update_fields=[
                    "attempt_count",
                    "status",
                    "last_attempt_at",
                    "locked_at",
                    "last_error_code",
                    "last_error_message",
                    "next_attempt_at",
                    "updated_at",
                ]
            )

    return sent_count


def _get_notification_log_retention_days() -> int:
    """Read notification_logs.retention_days from SystemConfig, fallback to default."""
    return get_int_system_config_value(key="notification_logs.retention_days")


@register(
    "cleanup_notification_logs",
    schedule=DailyAt(hour=3, minute=5),
    description="Deletes old notification audit logs based on your retention settings.",
)
def cleanup_notification_logs() -> int:
    """
    Delete NotificationLog records older than the configured retention period.

    Returns the count of deleted records.
    """
    retention_days = _get_notification_log_retention_days()
    if retention_days <= 0:
        return 0

    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted_count, _ = NotificationLog.objects.filter(created_at__lt=cutoff).delete()

    if deleted_count > 0:
        logger.info(
            "Cleaned up %d notification logs older than %d days (cutoff: %s)",
            deleted_count,
            retention_days,
            cutoff.isoformat(),
        )

    return deleted_count


def _get_notification_delivery_retention_days() -> int:
    """Read notification_deliveries.retention_days from SystemConfig, fallback to default."""
    return get_int_system_config_value(key="notification_deliveries.retention_days")


@register(
    "cleanup_notification_deliveries",
    schedule=DailyAt(hour=3, minute=7),
    description="Deletes old sent/dead notification deliveries based on your retention settings.",
)
def cleanup_notification_deliveries() -> int:
    """
    Delete sent/dead NotificationDelivery records older than the configured retention period.

    Returns the count of deleted records.
    """
    retention_days = _get_notification_delivery_retention_days()
    if retention_days <= 0:
        return 0

    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted_count, _ = NotificationDelivery.objects.filter(
        status__in=[NotificationDelivery.Status.SENT, NotificationDelivery.Status.DEAD],
        created_at__lt=cutoff,
    ).delete()

    if deleted_count > 0:
        logger.info(
            "Cleaned up %d notification deliveries older than %d days (cutoff: %s)",
            deleted_count,
            retention_days,
            cutoff.isoformat(),
        )

    return deleted_count
