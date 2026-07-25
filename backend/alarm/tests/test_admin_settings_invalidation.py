from __future__ import annotations

from django.contrib.admin.sites import AdminSite
from django.test import TestCase
from integrations_zigbee2mqtt import runtime as z2m_runtime

from alarm.admin import AlarmSettingsEntryAdmin, AlarmSettingsProfileAdmin
from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.tests.settings_test_utils import reset_cached_settings_snapshots
from alarm.use_cases.settings_profile import ensure_active_settings_profile

_Z2M_ENABLED = {"enabled": True, "base_topic": "zigbee2mqtt"}
_Z2M_DISABLED = {"enabled": False, "base_topic": "zigbee2mqtt"}


class AlarmSettingsAdminInvalidationTests(TestCase):
    """Admin writes bypass the settings views and profile use cases that normally send
    `settings_profile_changed`, so the admin must send it itself — otherwise the
    process-local ingest snapshots from ADR-0103 serve stale settings until restart, and
    an admin edit to the `zigbee2mqtt`/`frigate` entry silently fails to take effect."""

    def setUp(self) -> None:
        self.profile = ensure_active_settings_profile()
        self.site = AdminSite()
        reset_cached_settings_snapshots()

    def tearDown(self) -> None:
        reset_cached_settings_snapshots()

    def _make_entry(self, value: dict) -> AlarmSettingsEntry:
        entry, _ = AlarmSettingsEntry.objects.update_or_create(
            profile=self.profile,
            key="zigbee2mqtt",
            defaults={"value_type": "json", "value": value},
        )
        return entry

    def test_saving_entry_invalidates_ingest_snapshot(self) -> None:
        entry = self._make_entry(_Z2M_ENABLED)
        self.assertTrue(z2m_runtime.get_settings().enabled, "precondition: snapshot warmed as enabled")

        entry.value = _Z2M_DISABLED
        model_admin = AlarmSettingsEntryAdmin(AlarmSettingsEntry, self.site)
        with self.captureOnCommitCallbacks(execute=True):
            model_admin.save_model(None, entry, None, True)

        self.assertFalse(z2m_runtime.get_settings().enabled)

    def test_deleting_entry_invalidates_ingest_snapshot(self) -> None:
        """Removing an entry reverts that setting to its registry default, which the
        caches have to observe as well."""
        entry = self._make_entry(_Z2M_DISABLED)
        self.assertFalse(z2m_runtime.get_settings().enabled, "precondition: snapshot warmed as disabled")

        model_admin = AlarmSettingsEntryAdmin(AlarmSettingsEntry, self.site)
        with self.captureOnCommitCallbacks(execute=True):
            model_admin.delete_model(None, entry)

        # Default for the zigbee2mqtt setting is disabled, so assert the DB was re-read
        # rather than the snapshot object being handed back again.
        self.assertIsNone(z2m_runtime._settings_snapshot)

    def test_bulk_deleting_entries_invalidates_ingest_snapshot(self) -> None:
        self._make_entry(_Z2M_ENABLED)
        self.assertTrue(z2m_runtime.get_settings().enabled, "precondition: snapshot warmed as enabled")

        queryset = AlarmSettingsEntry.objects.filter(profile=self.profile, key="zigbee2mqtt")
        model_admin = AlarmSettingsEntryAdmin(AlarmSettingsEntry, self.site)
        with self.captureOnCommitCallbacks(execute=True):
            model_admin.delete_queryset(None, queryset)

        self.assertIsNone(z2m_runtime._settings_snapshot)

    def test_saving_profile_invalidates_ingest_snapshot(self) -> None:
        """Toggling a profile's is_active in the admin switches which profile settings are
        read from, so every cached snapshot has to be dropped."""
        self._make_entry(_Z2M_ENABLED)
        self.assertTrue(z2m_runtime.get_settings().enabled, "precondition: snapshot warmed as enabled")

        model_admin = AlarmSettingsProfileAdmin(AlarmSettingsProfile, self.site)
        with self.captureOnCommitCallbacks(execute=True):
            model_admin.save_model(None, self.profile, None, True)

        self.assertIsNone(z2m_runtime._settings_snapshot)
