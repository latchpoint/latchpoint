"""The HA app's runtime hooks: startup applies the stream, and profile changes reconnect it (#120)."""

from __future__ import annotations

from django.test import TestCase

from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.tests.settings_test_utils import EncryptionTestMixin
from alarm.use_cases.settings_profile import (
    activate_settings_profile,
    create_settings_profile,
    update_settings_profile,
)
from integrations_home_assistant.connection import get_cached_connection
from integrations_home_assistant.state_stream import _RuntimeSettings
from integrations_home_assistant.tests.stream_test_utils import FakeSessionStream, run_app_ready

_OLD = {"enabled": True, "base_url": "http://ha:8123", "token": "token"}
_NEW = {"enabled": True, "base_url": "http://ha-new:8123", "token": "new-token"}


def _set_ha_settings(profile: AlarmSettingsProfile, value: dict) -> None:
    entry = AlarmSettingsEntry.objects.get(profile=profile, key="home_assistant")
    entry.set_value_with_encryption(value)


def _ha_entry_changes(value: dict) -> dict:
    return {"entries": [{"key": "home_assistant", "value": value}]}


class HomeAssistantAppHooksTests(EncryptionTestMixin, TestCase):
    def setUp(self):
        self.profile = create_settings_profile(name="Home")
        activate_settings_profile(profile=self.profile)
        _set_ha_settings(self.profile, _OLD)
        self.fake = FakeSessionStream(self)
        self.stream = self.fake.stream

    def _start_app(self):
        run_app_ready(self)
        return self.fake.wait_for_session()

    def _assert_reconnected_on_new_settings(self, old_session):
        old_thread, _, _, old_stop = old_session
        self.assertTrue(self.stream.wait_for_background_apply(timeout=5))
        thread, ws_url, token, stop = self.fake.wait_for_session()

        self.assertEqual(get_cached_connection().token, "new-token")
        self.assertEqual(self.stream._settings, _RuntimeSettings(**_NEW))
        self.assertEqual((ws_url, token), ("ws://ha-new:8123/api/websocket", "new-token"))
        self.assertIsNot(thread, old_thread)
        self.assertTrue(old_stop.is_set())
        self.assertTrue(thread.is_alive())
        self.assertFalse(stop.is_set())

    def test_startup_applies_the_active_profiles_settings(self):
        thread, ws_url, token, stop = self._start_app()

        self.assertEqual(get_cached_connection().token, "token")
        self.assertEqual(self.stream._settings, _RuntimeSettings(**_OLD))
        self.assertEqual((ws_url, token), ("ws://ha:8123/api/websocket", "token"))
        self.assertIs(thread, self.stream._thread)
        self.assertTrue(thread.is_alive())
        self.assertFalse(stop.is_set())

    def test_activating_a_profile_reconnects_on_its_settings(self):
        other = create_settings_profile(name="Away")
        _set_ha_settings(other, _NEW)
        old_session = self._start_app()

        with self.captureOnCommitCallbacks(execute=True):
            activate_settings_profile(profile=other)

        self._assert_reconnected_on_new_settings(old_session)

    def test_updating_the_active_profiles_home_assistant_entry_reconnects(self):
        old_session = self._start_app()

        with self.captureOnCommitCallbacks(execute=True):
            update_settings_profile(profile=self.profile, changes=_ha_entry_changes(_NEW))

        self._assert_reconnected_on_new_settings(old_session)

    def test_profile_change_that_leaves_ha_alone_keeps_the_session(self):
        old_thread, _, _, old_stop = self._start_app()

        with self.captureOnCommitCallbacks(execute=True):
            update_settings_profile(profile=self.profile, changes={"entries": [{"key": "delay_time", "value": 45}]})

        self.assertTrue(self.stream.wait_for_background_apply(timeout=5))
        self.assertEqual(len(self.fake.sessions), 1)
        self.assertIs(self.stream._thread, old_thread)
        self.assertFalse(old_stop.is_set())

    def test_disabling_ha_in_the_profile_stops_the_stream(self):
        old_thread, _, _, old_stop = self._start_app()

        with self.captureOnCommitCallbacks(execute=True):
            update_settings_profile(profile=self.profile, changes=_ha_entry_changes({**_OLD, "enabled": False}))

        self.assertTrue(self.stream.wait_for_background_apply(timeout=5))
        old_thread.join(timeout=5)
        self.assertFalse(old_thread.is_alive())
        self.assertTrue(old_stop.is_set())
        self.assertFalse(self.stream._settings.enabled)
