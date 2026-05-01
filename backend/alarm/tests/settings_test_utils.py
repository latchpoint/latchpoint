from __future__ import annotations

import os

from cryptography.fernet import Fernet

from alarm.crypto import SettingsEncryption
from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile, AlarmState
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY

ARMED_STATES_FOR_TESTS = (
    AlarmState.ARMED_HOME,
    AlarmState.ARMED_AWAY,
    AlarmState.ARMED_NIGHT,
    AlarmState.ARMED_VACATION,
)

# Per-process test key (random each import) — never used in production
TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


class EncryptionTestMixin:
    """Mixin for tests that need the SettingsEncryption singleton.

    Sets ``SETTINGS_ENCRYPTION_KEY`` in the environment before any test
    runs and tears it down after, resetting the singleton both times so
    the test-key is always active within the class and cleaned up after.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ["SETTINGS_ENCRYPTION_KEY"] = TEST_ENCRYPTION_KEY
        SettingsEncryption.reset()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("SETTINGS_ENCRYPTION_KEY", None)
        SettingsEncryption.reset()
        super().tearDownClass()


# Deprecated settings not in registry but still supported in tests
DEPRECATED_SETTINGS = {
    "home_assistant_notify": "json",
}


def _apply_arming_time(
    profile: AlarmSettingsProfile,
    value: int,
    *,
    states: tuple[str, ...] = ARMED_STATES_FOR_TESTS,
) -> None:
    """Set arming_time per-state in state_overrides for the given armed states."""
    existing = AlarmSettingsEntry.objects.filter(profile=profile, key="state_overrides").first()
    overrides = (existing.value if existing else {}) or {}
    for state in states:
        overrides.setdefault(state, {})["arming_time"] = value
    AlarmSettingsEntry.objects.update_or_create(
        profile=profile,
        key="state_overrides",
        defaults={"value_type": "json", "value": overrides},
    )
    if hasattr(profile, "_settings_cache"):
        delattr(profile, "_settings_cache")


def set_profile_setting(profile: AlarmSettingsProfile, key: str, value):
    # Legacy test shorthand: arming_time was a global setting before per-state
    # overrides became the only path. Expand to overrides for all 4 armed states
    # so existing tests keep working without each one having to spell it out.
    if key == "arming_time":
        _apply_arming_time(profile, value)
        return

    # Check registry first, then deprecated settings
    definition = ALARM_PROFILE_SETTINGS_BY_KEY.get(key)
    if definition:
        value_type = definition.value_type
    elif key in DEPRECATED_SETTINGS:
        value_type = DEPRECATED_SETTINGS[key]
    else:
        raise KeyError(f"Unknown setting key: {key}")

    AlarmSettingsEntry.objects.update_or_create(
        profile=profile,
        key=key,
        defaults={"value_type": value_type, "value": value},
    )
    if hasattr(profile, "_settings_cache"):
        delattr(profile, "_settings_cache")


def set_profile_settings(profile: AlarmSettingsProfile, **values):
    # Apply state_overrides before the arming_time shorthand so explicit
    # per-state values win and arming_time only fills the remaining gaps.
    arming_time = values.pop("arming_time", None)
    explicit_overrides = values.pop("state_overrides", None)

    for key, value in values.items():
        set_profile_setting(profile, key, value)

    if explicit_overrides is not None:
        set_profile_setting(profile, "state_overrides", explicit_overrides)

    if arming_time is not None:
        skip = set()
        if isinstance(explicit_overrides, dict):
            for state, override in explicit_overrides.items():
                if isinstance(override, dict) and "arming_time" in override:
                    skip.add(state)
        target = tuple(s for s in ARMED_STATES_FOR_TESTS if s not in skip)
        if target:
            _apply_arming_time(profile, arming_time, states=target)
