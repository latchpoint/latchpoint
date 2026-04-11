"""Tests for NotificationProvider model-layer encryption methods (ADR 0079 Phase 2)."""

from __future__ import annotations

from django.test import TestCase

from alarm.crypto import ENCRYPTED_PREFIX, SettingsEncryption
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import EncryptionTestMixin
from notifications.models import NotificationProvider


class NotificationProviderEncryptionTests(EncryptionTestMixin, TestCase):
    """Tests for NotificationProvider encrypt/decrypt/mask methods."""

    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    # ------------------------------------------------------------------
    # get_decrypted_config
    # ------------------------------------------------------------------

    def test_get_decrypted_config_pushbullet(self):
        crypto = SettingsEncryption.get()
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="PB",
            provider_type="pushbullet",
            config={
                "access_token": crypto.encrypt("pb-token-123"),
                "target_type": "all",
            },
        )
        result = provider.get_decrypted_config()
        self.assertEqual(result["access_token"], "pb-token-123")
        self.assertEqual(result["target_type"], "all")

    def test_get_decrypted_config_discord(self):
        crypto = SettingsEncryption.get()
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="Discord",
            provider_type="discord",
            config={
                "webhook_url": crypto.encrypt("https://discord.com/api/webhooks/123/abc"),
                "username": "Latchpoint",
            },
        )
        result = provider.get_decrypted_config()
        self.assertEqual(result["webhook_url"], "https://discord.com/api/webhooks/123/abc")
        self.assertEqual(result["username"], "Latchpoint")

    def test_get_decrypted_config_no_encrypted_fields(self):
        """Home Assistant handler has no encrypted fields."""
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="HA Notify",
            provider_type="home_assistant",
            config={"service": "notify.mobile_app"},
        )
        result = provider.get_decrypted_config()
        self.assertEqual(result, {"service": "notify.mobile_app"})

    def test_get_decrypted_config_unknown_provider_type(self):
        """Unknown provider type returns config as-is."""
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="Future",
            provider_type="telegram",
            config={"bot_token": "tok123"},
        )
        result = provider.get_decrypted_config()
        self.assertEqual(result, {"bot_token": "tok123"})

    # ------------------------------------------------------------------
    # get_masked_config
    # ------------------------------------------------------------------

    def test_get_masked_config_slack(self):
        crypto = SettingsEncryption.get()
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="Slack",
            provider_type="slack",
            config={
                "bot_token": crypto.encrypt("xoxb-123"),
                "default_channel": "#alerts",
            },
        )
        result = provider.get_masked_config()
        self.assertNotIn("bot_token", result)
        self.assertTrue(result["has_bot_token"])
        self.assertEqual(result["default_channel"], "#alerts")

    def test_get_masked_config_webhook_empty_secret(self):
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="WH",
            provider_type="webhook",
            config={"url": "https://example.com", "auth_value": ""},
        )
        result = provider.get_masked_config()
        self.assertFalse(result["has_auth_value"])
        self.assertEqual(result["url"], "https://example.com")

    # ------------------------------------------------------------------
    # set_config_with_encryption
    # ------------------------------------------------------------------

    def test_set_config_encrypts_secret_fields(self):
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="PB",
            provider_type="pushbullet",
            config={},
        )
        provider.set_config_with_encryption(
            {
                "access_token": "new-pb-token",
                "target_type": "all",
            }
        )
        provider.refresh_from_db()

        self.assertTrue(provider.config["access_token"].startswith(ENCRYPTED_PREFIX))
        self.assertEqual(provider.config["target_type"], "all")
        self.assertEqual(provider.get_decrypted_config()["access_token"], "new-pb-token")

    def test_set_config_partial_preserves_existing_secret(self):
        crypto = SettingsEncryption.get()
        original = crypto.encrypt("keep-this-token")
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="Discord",
            provider_type="discord",
            config={"webhook_url": original, "username": "Old"},
        )
        provider.set_config_with_encryption({"username": "New"})
        provider.refresh_from_db()

        self.assertEqual(provider.config["webhook_url"], original)
        self.assertEqual(provider.config["username"], "New")

    def test_set_config_empty_secret_preserves_existing(self):
        crypto = SettingsEncryption.get()
        original = crypto.encrypt("xoxb-original")
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="Slack",
            provider_type="slack",
            config={"bot_token": original, "default_channel": "#c"},
        )
        provider.set_config_with_encryption({"bot_token": ""})
        provider.refresh_from_db()

        self.assertEqual(provider.config["bot_token"], original)

    def test_set_config_full_replace(self):
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="WH",
            provider_type="webhook",
            config={"url": "https://old.com", "auth_value": ""},
        )
        provider.set_config_with_encryption(
            {"url": "https://new.com", "auth_value": "Bearer xyz"},
            partial=False,
        )
        provider.refresh_from_db()

        self.assertEqual(provider.config["url"], "https://new.com")
        self.assertTrue(provider.config["auth_value"].startswith(ENCRYPTED_PREFIX))
