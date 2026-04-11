"""Tests for the centralized encryption service (ADR 0079 Phase 1)."""

from __future__ import annotations

from django.test import TestCase

from alarm.crypto import ENCRYPTED_PREFIX, SettingsEncryption
from alarm.tests.settings_test_utils import EncryptionTestMixin


class SettingsEncryptionTests(EncryptionTestMixin, TestCase):
    """Core encrypt / decrypt / mask operations."""

    def test_encrypt_returns_prefixed_string(self):
        crypto = SettingsEncryption.get()
        result = crypto.encrypt("my-secret-token")
        self.assertTrue(result.startswith(ENCRYPTED_PREFIX))

    def test_decrypt_round_trip(self):
        crypto = SettingsEncryption.get()
        encrypted = crypto.encrypt("my-secret-token")
        self.assertEqual(crypto.decrypt(encrypted), "my-secret-token")

    def test_encrypt_empty_returns_empty(self):
        crypto = SettingsEncryption.get()
        self.assertEqual(crypto.encrypt(""), "")

    def test_decrypt_empty_returns_empty(self):
        crypto = SettingsEncryption.get()
        self.assertEqual(crypto.decrypt(""), "")

    def test_encrypt_idempotent(self):
        """Encrypting an already-encrypted value returns it unchanged."""
        crypto = SettingsEncryption.get()
        encrypted = crypto.encrypt("secret")
        self.assertEqual(crypto.encrypt(encrypted), encrypted)

    def test_decrypt_rejects_plaintext(self):
        crypto = SettingsEncryption.get()
        with self.assertRaises(ValueError) as ctx:
            crypto.decrypt("plaintext-value")
        self.assertIn(ENCRYPTED_PREFIX, str(ctx.exception))

    def test_is_encrypted(self):
        crypto = SettingsEncryption.get()
        encrypted = crypto.encrypt("value")
        self.assertTrue(crypto.is_encrypted(encrypted))
        self.assertFalse(crypto.is_encrypted("plaintext"))
        self.assertFalse(crypto.is_encrypted(""))

    # ------------------------------------------------------------------
    # Dict-level helpers
    # ------------------------------------------------------------------

    def test_encrypt_fields(self):
        crypto = SettingsEncryption.get()
        config = {"host": "localhost", "password": "secret", "port": 1883}
        result = crypto.encrypt_fields(config, ["password"])

        self.assertEqual(result["host"], "localhost")
        self.assertEqual(result["port"], 1883)
        self.assertTrue(result["password"].startswith(ENCRYPTED_PREFIX))
        # Original dict is not mutated
        self.assertEqual(config["password"], "secret")

    def test_decrypt_fields(self):
        crypto = SettingsEncryption.get()
        config = {"host": "localhost", "password": crypto.encrypt("secret")}
        result = crypto.decrypt_fields(config, ["password"])

        self.assertEqual(result["password"], "secret")
        self.assertEqual(result["host"], "localhost")

    def test_encrypt_fields_skips_empty(self):
        crypto = SettingsEncryption.get()
        config = {"token": "", "url": "http://example.com"}
        result = crypto.encrypt_fields(config, ["token"])
        self.assertEqual(result["token"], "")

    def test_encrypt_fields_skips_missing(self):
        crypto = SettingsEncryption.get()
        config = {"url": "http://example.com"}
        result = crypto.encrypt_fields(config, ["token"])
        self.assertNotIn("token", result)

    def test_mask_fields(self):
        crypto = SettingsEncryption.get()
        encrypted_pw = crypto.encrypt("secret")
        config = {"host": "localhost", "password": encrypted_pw, "token": ""}

        result = crypto.mask_fields(config, ["password", "token"])

        self.assertEqual(result["host"], "localhost")
        self.assertTrue(result["has_password"])
        self.assertFalse(result["has_token"])
        # Original secret fields are removed
        self.assertNotIn("password", result)
        self.assertNotIn("token", result)

    def test_mask_fields_missing_key(self):
        crypto = SettingsEncryption.get()
        config = {"host": "localhost"}
        result = crypto.mask_fields(config, ["password"])
        self.assertFalse(result["has_password"])


class SettingsEncryptionSingletonTests(EncryptionTestMixin, TestCase):
    """Singleton lifecycle."""

    def test_get_returns_same_instance(self):
        a = SettingsEncryption.get()
        b = SettingsEncryption.get()
        self.assertIs(a, b)

    def test_reset_clears_singleton(self):
        a = SettingsEncryption.get()
        SettingsEncryption.reset()
        b = SettingsEncryption.get()
        self.assertIsNot(a, b)
