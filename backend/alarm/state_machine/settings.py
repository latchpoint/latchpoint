from __future__ import annotations

from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY

from .errors import TransitionError
from alarm.use_cases.settings_profile import ensure_active_settings_profile


def get_active_settings_profile() -> AlarmSettingsProfile:
    """Return the active settings profile with a best-effort in-memory settings cache populated."""
    profile = ensure_active_settings_profile()
    # Best-effort: keep a local cache of settings values to avoid per-key queries.
    preloaded = AlarmSettingsEntry.objects.filter(profile=profile).only("key", "value")
    setattr(profile, "_settings_cache", {e.key: e.value for e in preloaded})
    return profile


def _settings_cache(profile: AlarmSettingsProfile) -> dict[str, object]:
    """Return the profile's in-memory settings cache, populating it from DB if missing."""
    cached = getattr(profile, "_settings_cache", None)
    if isinstance(cached, dict):
        return cached
    rows = AlarmSettingsEntry.objects.filter(profile=profile).only("key", "value")
    cache = {row.key: row.value for row in rows}
    setattr(profile, "_settings_cache", cache)
    return cache


def get_setting_value(profile: AlarmSettingsProfile, key: str) -> object:
    """Return the raw setting value for `key`, falling back to its registered default."""
    definition = ALARM_PROFILE_SETTINGS_BY_KEY.get(key)
    if not definition:
        raise TransitionError(f"Unknown setting key: {key}")
    return _settings_cache(profile).get(key, definition.default)


def get_setting_bool(profile: AlarmSettingsProfile, key: str) -> bool:
    """Return a setting value coerced to bool."""
    value = get_setting_value(profile, key)
    return bool(value)


def get_setting_int(profile: AlarmSettingsProfile, key: str) -> int:
    """Return a setting value coerced to int, falling back to default on parse errors."""
    value = get_setting_value(profile, key)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        definition = ALARM_PROFILE_SETTINGS_BY_KEY[key]
        return int(definition.default)  # type: ignore[arg-type]


def get_setting_json(profile: AlarmSettingsProfile, key: str):
    """Return a setting value (typically a dict/list) without further coercion."""
    return get_setting_value(profile, key)
