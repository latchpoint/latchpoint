"""Background tasks for the Frigate integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from integrations_frigate.models import FrigateDetection
from integrations_frigate.runtime import get_settings
from scheduler import Every, register

logger = logging.getLogger(__name__)

def _is_frigate_active() -> bool:
    """Return True if Frigate integration is enabled (scheduler gating predicate)."""
    try:
        return bool(get_settings().enabled)
    except Exception:
        return False


@register(
    "cleanup_frigate_detections",
    schedule=Every(seconds=3600, jitter=60),
    description="Deletes old camera detections based on your configured retention settings.",
    enabled_when=_is_frigate_active,
)
def cleanup_frigate_detections() -> int:
    """
    Delete FrigateDetection records older than the configured retention period.

    Uses the existing `retention_seconds` setting from Frigate configuration.
    Returns the count of deleted records.
    """
    settings = get_settings()
    if not settings.enabled:
        return 0

    retention_seconds = settings.retention_seconds
    cutoff = timezone.now() - timedelta(seconds=retention_seconds)

    deleted_count, _ = FrigateDetection.objects.filter(observed_at__lt=cutoff).delete()

    if deleted_count > 0:
        logger.info(
            "Cleaned up %d Frigate detections older than %d seconds (cutoff: %s)",
            deleted_count,
            retention_seconds,
            cutoff.isoformat(),
        )

    return deleted_count
