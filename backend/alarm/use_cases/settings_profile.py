from __future__ import annotations

import logging

from django.db import transaction
from rest_framework.exceptions import ValidationError

from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.settings_registry import ALARM_PROFILE_SETTINGS, ALARM_PROFILE_SETTINGS_BY_KEY

logger = logging.getLogger(__name__)


def _ensure_profile_entries(profile: AlarmSettingsProfile) -> None:
    """Ensure the profile has entries for all registered alarm profile settings."""
    existing = {row.key: row for row in AlarmSettingsEntry.objects.filter(profile=profile)}
    missing = [d for d in ALARM_PROFILE_SETTINGS if d.key not in existing]
    if not missing:
        return
    AlarmSettingsEntry.objects.bulk_create(
        [
            AlarmSettingsEntry(
                profile=profile,
                key=d.key,
                value_type=d.value_type,
                value=d.default,
            )
            for d in missing
        ]
    )


def ensure_active_settings_profile(*, timezone_name: str | None = None) -> AlarmSettingsProfile:
    """Return the active settings profile, creating/defaulting as needed and ensuring entries."""
    profile = AlarmSettingsProfile.objects.filter(is_active=True).first()
    if not profile:
        existing = AlarmSettingsProfile.objects.first()
        if existing:
            existing.is_active = True
            existing.save(update_fields=["is_active"])
            profile = existing
        else:
            profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    _ensure_profile_entries(profile)
    return profile


def list_settings_profiles():
    """Return all settings profiles in a stable order."""
    return AlarmSettingsProfile.objects.all().order_by("name", "id")


def create_settings_profile(*, name: str) -> AlarmSettingsProfile:
    """Create a new inactive settings profile with default entries."""
    profile = AlarmSettingsProfile.objects.create(name=name, is_active=False)
    _ensure_profile_entries(profile)
    return profile


def update_settings_profile(*, profile: AlarmSettingsProfile, changes: dict) -> AlarmSettingsProfile:
    """Update profile metadata and/or settings entries; emits a settings-changed signal on commit."""
    name = changes.pop("name", None)
    if name is not None:
        profile.name = name
        profile.save(update_fields=["name"])

    entries = changes.pop("entries", None)
    if entries is not None:
        for entry in entries:
            key = entry.get("key")
            value = entry.get("value")
            if key not in ALARM_PROFILE_SETTINGS_BY_KEY:
                raise ValidationError({"detail": f"Unknown setting key: {key}"})
            definition = ALARM_PROFILE_SETTINGS_BY_KEY[key]
            AlarmSettingsEntry.objects.update_or_create(
                profile=profile,
                key=key,
                defaults={"value": value, "value_type": definition.value_type},
            )
        try:
            from alarm.signals import settings_profile_changed

            transaction.on_commit(
                lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated")
            )
        except Exception:
            logger.debug("Signal emission failed", exc_info=True)
    return profile


def delete_settings_profile(*, profile: AlarmSettingsProfile) -> None:
    """Delete a profile unless it is currently active."""
    if profile.is_active:
        raise ValidationError({"detail": "Cannot delete the active settings profile."})
    profile.delete()


def activate_settings_profile(*, profile: AlarmSettingsProfile) -> AlarmSettingsProfile:
    """Make `profile` the active settings profile and deactivate others."""
    with transaction.atomic():
        AlarmSettingsProfile.objects.filter(is_active=True).exclude(id=profile.id).update(is_active=False)
        if not profile.is_active:
            profile.is_active = True
            profile.save(update_fields=["is_active"])
        try:
            from alarm.signals import settings_profile_changed

            transaction.on_commit(
                lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="activated")
            )
        except Exception:
            logger.debug("Signal emission failed", exc_info=True)
    return profile
