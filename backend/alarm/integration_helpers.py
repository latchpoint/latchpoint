"""
Shared helpers for reading and writing integration enabled state from AlarmSettingsEntry.

The ``enabled`` flag for each integration is stored in the DB (``AlarmSettingsEntry``)
and toggled via the UI.  Connection config (URLs, credentials) lives in env vars.
"""

from __future__ import annotations


def get_integration_enabled(key: str) -> bool:
    """Read the enabled flag from AlarmSettingsEntry for a given integration."""
    from alarm.state_machine.settings import get_active_settings_profile, get_setting_json

    profile = get_active_settings_profile()
    raw = get_setting_json(profile, key) or {}
    return bool(raw.get("enabled", False)) if isinstance(raw, dict) else False


def set_integration_enabled(key: str, enabled: bool) -> None:
    """Set the enabled flag in AlarmSettingsEntry and emit settings_profile_changed."""
    from django.db import transaction

    from alarm.models import AlarmSettingsEntry
    from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
    from alarm.signals import settings_profile_changed
    from alarm.state_machine.settings import get_setting_json
    from alarm.use_cases.settings_profile import ensure_active_settings_profile

    profile = ensure_active_settings_profile()
    definition = ALARM_PROFILE_SETTINGS_BY_KEY[key]
    current = get_setting_json(profile, key) or {}
    if not isinstance(current, dict):
        current = {}
    current["enabled"] = enabled
    AlarmSettingsEntry.objects.update_or_create(
        profile=profile,
        key=key,
        defaults={"value": current, "value_type": definition.value_type},
    )
    transaction.on_commit(lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated"))
