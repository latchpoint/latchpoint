"""Tests for model-layer encryption methods (ADR 0079 Phase 2)."""

from __future__ import annotations

from django.test import TestCase

from alarm.crypto import ENCRYPTED_PREFIX, SettingsEncryption
from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.tests.settings_test_utils import EncryptionTestMixin


class AlarmSettingsEntryEncryptionTests(EncryptionTestMixin, TestCase):
    """Tests for AlarmSettingsEntry encrypt/decrypt/mask methods."""

    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    # ------------------------------------------------------------------
    # get_decrypted_value
    # ------------------------------------------------------------------

    def test_get_decrypted_value_with_encrypted_field(self):
        crypto = SettingsEncryption.get()
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="home_assistant",
            value_type="json",
            value={
                "enabled": True,
                "base_url": "http://ha.local:8123",
                "token": crypto.encrypt("my-ha-token"),
                "connect_timeout_seconds": 2,
            },
        )
        result = entry.get_decrypted_value()
        self.assertEqual(result["token"], "my-ha-token")
        self.assertEqual(result["base_url"], "http://ha.local:8123")
        self.assertTrue(result["enabled"])

    def test_get_decrypted_value_no_encrypted_fields(self):
        """Settings without encrypted_fields return value as-is."""
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="delay_time",
            value_type="integer",
            value=60,
        )
        self.assertEqual(entry.get_decrypted_value(), 60)

    def test_get_decrypted_value_unknown_key(self):
        """Unknown keys (not in registry) return value as-is."""
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="unknown_setting",
            value_type="json",
            value={"foo": "bar"},
        )
        self.assertEqual(entry.get_decrypted_value(), {"foo": "bar"})

    # ------------------------------------------------------------------
    # get_masked_value
    # ------------------------------------------------------------------

    def test_get_masked_value_replaces_secret_with_has_field(self):
        crypto = SettingsEncryption.get()
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="mqtt",
            value_type="json",
            value={
                "enabled": True,
                "host": "mqtt.local",
                "password": crypto.encrypt("secret-pw"),
            },
        )
        result = entry.get_masked_value()
        self.assertNotIn("password", result)
        self.assertTrue(result["has_password"])
        self.assertEqual(result["host"], "mqtt.local")

    def test_get_masked_value_empty_secret(self):
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="mqtt",
            value_type="json",
            value={"enabled": False, "host": "localhost", "password": ""},
        )
        result = entry.get_masked_value()
        self.assertFalse(result["has_password"])

    def test_get_masked_value_no_encrypted_fields(self):
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="zigbee2mqtt",
            value_type="json",
            value={"enabled": False, "base_topic": "zigbee2mqtt"},
        )
        result = entry.get_masked_value()
        self.assertEqual(result, {"enabled": False, "base_topic": "zigbee2mqtt"})

    # ------------------------------------------------------------------
    # set_value_with_encryption
    # ------------------------------------------------------------------

    def test_set_value_encrypts_secret_fields(self):
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="home_assistant",
            value_type="json",
            value={"enabled": False, "base_url": "", "token": "", "connect_timeout_seconds": 2},
        )
        entry.set_value_with_encryption(
            {
                "enabled": True,
                "base_url": "http://ha.local:8123",
                "token": "my-new-token",
            }
        )
        entry.refresh_from_db()

        # Token should be encrypted in the DB
        self.assertTrue(entry.value["token"].startswith(ENCRYPTED_PREFIX))
        # Non-secret fields stored in plaintext
        self.assertEqual(entry.value["base_url"], "http://ha.local:8123")
        self.assertTrue(entry.value["enabled"])
        # Decrypted value should have plaintext token
        self.assertEqual(entry.get_decrypted_value()["token"], "my-new-token")

    def test_set_value_partial_preserves_existing_secret(self):
        """When a secret field is absent in the update, the existing encrypted value is kept."""
        crypto = SettingsEncryption.get()
        original_encrypted = crypto.encrypt("original-token")
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="home_assistant",
            value_type="json",
            value={"enabled": True, "base_url": "http://old.local", "token": original_encrypted},
        )
        # Update only the base_url, omitting token
        entry.set_value_with_encryption({"base_url": "http://new.local"})
        entry.refresh_from_db()

        self.assertEqual(entry.value["base_url"], "http://new.local")
        self.assertEqual(entry.value["token"], original_encrypted)

    def test_set_value_empty_secret_clears_existing(self):
        """An explicit empty string for a secret field clears the stored value."""
        crypto = SettingsEncryption.get()
        original_encrypted = crypto.encrypt("keep-me")
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="zwavejs",
            value_type="json",
            value={"enabled": True, "ws_url": "ws://z:3000", "api_token": original_encrypted},
        )
        entry.set_value_with_encryption({"api_token": ""})
        entry.refresh_from_db()

        self.assertEqual(entry.value["api_token"], "")

    def test_set_value_full_replace(self):
        """partial=False replaces the entire value dict."""
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="mqtt",
            value_type="json",
            value={"enabled": True, "host": "old", "password": ""},
        )
        entry.set_value_with_encryption(
            {"enabled": False, "host": "new", "password": "newpw"},
            partial=False,
        )
        entry.refresh_from_db()

        self.assertFalse(entry.value["enabled"])
        self.assertEqual(entry.value["host"], "new")
        self.assertTrue(entry.value["password"].startswith(ENCRYPTED_PREFIX))

    def test_set_value_no_encrypted_fields(self):
        """Settings without encrypted_fields work normally."""
        entry = AlarmSettingsEntry.objects.create(
            profile=self.profile,
            key="zigbee2mqtt",
            value_type="json",
            value={"enabled": False, "base_topic": "zigbee2mqtt"},
        )
        entry.set_value_with_encryption({"enabled": True})
        entry.refresh_from_db()

        self.assertTrue(entry.value["enabled"])
        self.assertEqual(entry.value["base_topic"], "zigbee2mqtt")
