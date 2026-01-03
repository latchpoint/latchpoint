from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from alarm.models import AlarmSettingsProfile
from integrations_home_assistant.models import HomeAssistantMqttAlarmEntityStatus
from alarm.use_cases.settings_profile import ensure_active_settings_profile


def _get_or_create_status(profile: AlarmSettingsProfile) -> HomeAssistantMqttAlarmEntityStatus:
    """Fetch or create the per-profile MQTT alarm entity status row."""
    status, _ = HomeAssistantMqttAlarmEntityStatus.objects.get_or_create(profile=profile)
    return status


def mark_discovery_published(*, when: datetime | None = None) -> None:
    """Record that discovery was published for the active profile."""
    profile = ensure_active_settings_profile()
    status = _get_or_create_status(profile)
    status.last_discovery_publish_at = when or timezone.now()
    status.save(update_fields=["last_discovery_publish_at", "updated_at"])


def mark_state_published(*, when: datetime | None = None) -> None:
    """Record that a state payload was published for the active profile."""
    profile = ensure_active_settings_profile()
    status = _get_or_create_status(profile)
    status.last_state_publish_at = when or timezone.now()
    status.save(update_fields=["last_state_publish_at", "updated_at"])


def mark_availability_published(*, when: datetime | None = None) -> None:
    """Record that an availability payload was published for the active profile."""
    profile = ensure_active_settings_profile()
    status = _get_or_create_status(profile)
    status.last_availability_publish_at = when or timezone.now()
    status.save(update_fields=["last_availability_publish_at", "updated_at"])


def mark_error(*, error: str, when: datetime | None = None) -> None:
    """Record the last publish/command processing error for the active profile."""
    profile = ensure_active_settings_profile()
    status = _get_or_create_status(profile)
    status.last_error_at = when or timezone.now()
    status.last_error = str(error or "")
    status.save(update_fields=["last_error_at", "last_error", "updated_at"])


def read_status() -> dict[str, object]:
    """Return a JSON-friendly status snapshot for the active profile."""
    profile = ensure_active_settings_profile()
    status = HomeAssistantMqttAlarmEntityStatus.objects.filter(profile=profile).first()
    if not status:
        return {
            "last_discovery_publish_at": None,
            "last_state_publish_at": None,
            "last_availability_publish_at": None,
            "last_error_at": None,
            "last_error": None,
        }
    return {
        "last_discovery_publish_at": status.last_discovery_publish_at.isoformat() if status.last_discovery_publish_at else None,
        "last_state_publish_at": status.last_state_publish_at.isoformat() if status.last_state_publish_at else None,
        "last_availability_publish_at": status.last_availability_publish_at.isoformat() if status.last_availability_publish_at else None,
        "last_error_at": status.last_error_at.isoformat() if status.last_error_at else None,
        "last_error": status.last_error or None,
    }
