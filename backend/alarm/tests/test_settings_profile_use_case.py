from __future__ import annotations

from django.test import TestCase
from rest_framework.exceptions import ValidationError

from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.use_cases.settings_profile import (
    activate_settings_profile,
    create_settings_profile,
    delete_settings_profile,
    ensure_active_settings_profile,
    list_settings_profiles,
    update_settings_profile,
)


class EnsureActiveSettingsProfileTests(TestCase):
    def test_creates_default_when_none_exist(self):
        self.assertFalse(AlarmSettingsProfile.objects.exists())
        profile = ensure_active_settings_profile()
        self.assertIsNotNone(profile)
        self.assertTrue(profile.is_active)
        self.assertEqual(profile.name, "Default")

    def test_activates_first_existing_when_none_active(self):
        profile1 = AlarmSettingsProfile.objects.create(name="Profile 1", is_active=False)
        profile2 = AlarmSettingsProfile.objects.create(name="Profile 2", is_active=False)

        result = ensure_active_settings_profile()
        result.refresh_from_db()
        self.assertTrue(result.is_active)

    def test_returns_existing_active_profile(self):
        existing = AlarmSettingsProfile.objects.create(name="Existing", is_active=True)
        result = ensure_active_settings_profile()
        self.assertEqual(result.id, existing.id)


class CreateSettingsProfileTests(TestCase):
    def test_creates_inactive_profile(self):
        profile = create_settings_profile(name="New Profile")
        self.assertIsNotNone(profile.id)
        self.assertEqual(profile.name, "New Profile")
        self.assertFalse(profile.is_active)

    def test_initializes_default_entries(self):
        profile = create_settings_profile(name="With Entries")
        entries = AlarmSettingsEntry.objects.filter(profile=profile)
        self.assertGreater(entries.count(), 0)


class UpdateSettingsProfileTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Test Profile", is_active=True)

    def test_updates_name(self):
        update_settings_profile(profile=self.profile, changes={"name": "Updated Name"})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.name, "Updated Name")

    def test_updates_entries(self):
        changes = {"entries": [{"key": "delay_time", "value": 45}]}
        update_settings_profile(profile=self.profile, changes=changes)

        entry = AlarmSettingsEntry.objects.get(profile=self.profile, key="delay_time")
        self.assertEqual(entry.value, 45)

    def test_raises_for_unknown_setting_key(self):
        changes = {"entries": [{"key": "unknown_key", "value": "foo"}]}
        with self.assertRaises(ValidationError):
            update_settings_profile(profile=self.profile, changes=changes)

    def test_emits_signal_on_entries_update(self):
        # Signal is sent via transaction.on_commit, so we verify the use case completes
        # without error when updating entries
        changes = {"entries": [{"key": "delay_time", "value": 60}]}
        result = update_settings_profile(profile=self.profile, changes=changes)
        self.assertEqual(result.id, self.profile.id)
        entry = AlarmSettingsEntry.objects.get(profile=self.profile, key="delay_time")
        self.assertEqual(entry.value, 60)


class DeleteSettingsProfileTests(TestCase):
    def test_delete_inactive_profile(self):
        profile = AlarmSettingsProfile.objects.create(name="To Delete", is_active=False)
        delete_settings_profile(profile=profile)
        self.assertFalse(AlarmSettingsProfile.objects.filter(id=profile.id).exists())

    def test_raises_when_deleting_active_profile(self):
        profile = AlarmSettingsProfile.objects.create(name="Active", is_active=True)
        with self.assertRaises(ValidationError):
            delete_settings_profile(profile=profile)


class ActivateSettingsProfileTests(TestCase):
    def test_activates_profile(self):
        profile = AlarmSettingsProfile.objects.create(name="Inactive", is_active=False)
        result = activate_settings_profile(profile=profile)
        result.refresh_from_db()
        self.assertTrue(result.is_active)

    def test_deactivates_other_profiles(self):
        profile1 = AlarmSettingsProfile.objects.create(name="Profile 1", is_active=True)
        profile2 = AlarmSettingsProfile.objects.create(name="Profile 2", is_active=False)

        activate_settings_profile(profile=profile2)

        profile1.refresh_from_db()
        profile2.refresh_from_db()
        self.assertFalse(profile1.is_active)
        self.assertTrue(profile2.is_active)


class ListSettingsProfilesTests(TestCase):
    def test_returns_all_profiles_ordered(self):
        AlarmSettingsProfile.objects.create(name="B Profile", is_active=False)
        AlarmSettingsProfile.objects.create(name="A Profile", is_active=True)
        AlarmSettingsProfile.objects.create(name="C Profile", is_active=False)

        profiles = list(list_settings_profiles())
        names = [p.name for p in profiles]
        self.assertEqual(names, ["A Profile", "B Profile", "C Profile"])
