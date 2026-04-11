from __future__ import annotations

import os

from cryptography.fernet import Fernet

from alarm.crypto import SettingsEncryption
from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY

# Deterministic test key — never used in production
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


def set_profile_setting(profile: AlarmSettingsProfile, key: str, value):
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
    for key, value in values.items():
        set_profile_setting(profile, key, value)
