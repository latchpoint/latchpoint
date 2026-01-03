from __future__ import annotations

from django.test import TestCase

from alarm.models import AlarmSettingsProfile
from alarm.state_machine.settings import get_active_settings_profile


class SettingsProfileTests(TestCase):
    def test_get_active_settings_profile_bootstraps_when_missing(self):
        profile = get_active_settings_profile()
        self.assertTrue(AlarmSettingsProfile.objects.filter(id=profile.id).exists())

    def test_get_active_settings_profile_returns_first_active(self):
        AlarmSettingsProfile.objects.create(name="Inactive", is_active=False)
        active = AlarmSettingsProfile.objects.create(name="Active", is_active=True)
        self.assertEqual(get_active_settings_profile().id, active.id)
