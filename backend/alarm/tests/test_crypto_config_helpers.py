from __future__ import annotations

import os

from django.test import SimpleTestCase

from alarm import crypto


class CryptoConfigHelpersTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self._prev_key = os.environ.get(crypto.SETTINGS_ENCRYPTION_KEY_ENV)
        crypto._get_fernet.cache_clear()
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        if self._prev_key is None:
            os.environ.pop(crypto.SETTINGS_ENCRYPTION_KEY_ENV, None)
        else:
            os.environ[crypto.SETTINGS_ENCRYPTION_KEY_ENV] = self._prev_key
        crypto._get_fernet.cache_clear()

    def test_mask_config_replaces_field_with_has_indicator(self):
        masked = crypto.mask_config({"token": "enc:abc", "enabled": True}, ["token"])
        self.assertEqual(masked, {"enabled": True, "has_token": True})

    def test_encrypt_config_normalizes_none_to_empty_string(self):
        encrypted = crypto.encrypt_config({"token": None, "enabled": True}, ["token"])
        self.assertEqual(encrypted, {"token": "", "enabled": True})

    def test_prepare_runtime_config_drops_unknown_keys(self):
        runtime = crypto.prepare_runtime_config(
            {"enabled": True, "unknown": "value"},
            encrypted_fields=["token"],
            defaults={"enabled": False, "token": ""},
        )
        self.assertEqual(runtime, {"enabled": True, "token": ""})

    def test_prepare_runtime_config_decrypts_encrypted_fields(self):
        from cryptography.fernet import Fernet

        os.environ[crypto.SETTINGS_ENCRYPTION_KEY_ENV] = Fernet.generate_key().decode("utf-8")
        crypto._get_fernet.cache_clear()

        encrypted = crypto.encrypt_secret("s3cr3t")
        self.assertTrue(encrypted.startswith(crypto.ENCRYPTION_PREFIX))

        runtime = crypto.prepare_runtime_config(
            {"token": encrypted},
            encrypted_fields=["token"],
            defaults={"enabled": False, "token": ""},
        )
        self.assertEqual(runtime["token"], "s3cr3t")

