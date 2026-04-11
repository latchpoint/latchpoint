"""
Shared helpers for querying integration enabled/configured state from DB settings.

These replace the old ``env_config.get_*_config()`` checks that read from env vars.
All state now lives in ``AlarmSettingsEntry`` (ADR 0079).
"""

from __future__ import annotations


def mqtt_enabled() -> bool:
    """Return True if MQTT is enabled and has a host configured."""
    from alarm.models import AlarmSettingsEntry
    from alarm.use_cases.settings_profile import ensure_active_settings_profile

    profile = ensure_active_settings_profile()
    try:
        entry = AlarmSettingsEntry.objects.get(profile=profile, key="mqtt")
    except AlarmSettingsEntry.DoesNotExist:
        return False
    cfg = entry.get_decrypted_value()
    return bool(cfg.get("enabled") and cfg.get("host"))


def zwavejs_enabled() -> bool:
    """Return True if Z-Wave JS is enabled and has a ws_url configured."""
    from alarm.models import AlarmSettingsEntry
    from alarm.use_cases.settings_profile import ensure_active_settings_profile

    profile = ensure_active_settings_profile()
    try:
        entry = AlarmSettingsEntry.objects.get(profile=profile, key="zwavejs")
    except AlarmSettingsEntry.DoesNotExist:
        return False
    cfg = entry.get_decrypted_value()
    return bool(cfg.get("enabled") and cfg.get("ws_url"))
