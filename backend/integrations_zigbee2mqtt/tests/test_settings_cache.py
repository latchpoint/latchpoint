from __future__ import annotations

from django.test import TestCase

from alarm.models import AlarmSettingsEntry
from alarm.signals import settings_profile_changed
from alarm.tests.settings_test_utils import set_profile_setting
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from integrations_zigbee2mqtt import runtime


class Zigbee2mqttSettingsCacheTests(TestCase):
    """ADR-0103: the ingest handler reads settings on every inbound MQTT message,
    so `get_settings()` caches a normalized snapshot and only re-reads the DB when
    empty or after `settings_profile_changed` invalidates it."""

    def setUp(self) -> None:
        runtime._settings_snapshot = None
        self.profile = ensure_active_settings_profile()
        AlarmSettingsEntry.objects.update_or_create(
            profile=self.profile,
            key="zigbee2mqtt",
            defaults={"value_type": "json", "value": {"enabled": True, "base_topic": "zigbee2mqtt"}},
        )

    def tearDown(self) -> None:
        runtime._settings_snapshot = None

    def test_warm_cache_reads_issue_no_settings_queries(self) -> None:
        first = runtime.get_settings()  # warms the cache (DB read)
        self.assertTrue(first.enabled)
        with self.assertNumQueries(0):
            for _ in range(5):
                runtime.get_settings()

    def test_profile_changed_signal_invalidates_cache(self) -> None:
        self.assertTrue(runtime.get_settings().enabled)  # warm with enabled=True
        AlarmSettingsEntry.objects.filter(profile=self.profile, key="zigbee2mqtt").update(
            value={"enabled": False, "base_topic": "zigbee2mqtt"}
        )
        # Stale cache still reports the old value until the signal invalidates it.
        self.assertTrue(runtime.get_settings().enabled)
        settings_profile_changed.send(sender=None, profile_id=self.profile.id, reason="test")
        self.assertFalse(runtime.get_settings().enabled)

    def test_test_helper_write_invalidates_cache(self) -> None:
        """Tests write settings rows directly, bypassing the signal, so
        `set_profile_setting` clears the snapshot itself — otherwise a value warmed by an
        earlier test would leak in and make assertions order-dependent."""
        self.assertTrue(runtime.get_settings().enabled)  # warm with enabled=True
        set_profile_setting(self.profile, "zigbee2mqtt", {"enabled": False, "base_topic": "zigbee2mqtt"})
        self.assertFalse(runtime.get_settings().enabled)
