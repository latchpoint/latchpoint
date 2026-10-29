"""The post-migrate encryption key check (ADR 0079) skips until the settings table exists (#169)."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet
from django.apps import apps
from django.db import DEFAULT_DB_ALIAS, connection
from django.test import TestCase

from alarm.apps import _validate_encryption_key
from alarm.crypto import ENCRYPTED_PREFIX, SettingsEncryption
from alarm.models import AlarmSettingsEntry
from alarm.tests.settings_test_utils import TEST_ENCRYPTION_KEY, EncryptionTestMixin, set_profile_settings
from alarm.use_cases.settings_profile import ensure_active_settings_profile


def _post_migrate() -> None:
    _validate_encryption_key(sender=apps.get_app_config("alarm"), using=DEFAULT_DB_ALIAS)


class ValidateEncryptionKeyTests(EncryptionTestMixin, TestCase):
    def _store_encrypted_mqtt_password(self) -> None:
        password = SettingsEncryption.get().encrypt("broker-secret")
        self.assertTrue(password.startswith(ENCRYPTED_PREFIX))
        set_profile_settings(ensure_active_settings_profile(), mqtt={"enabled": True, "password": password})

    def _use_key(self, key: str) -> None:
        os.environ["SETTINGS_ENCRYPTION_KEY"] = key
        SettingsEncryption.reset()
        self.addCleanup(SettingsEncryption.reset)
        self.addCleanup(os.environ.__setitem__, "SETTINGS_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)

    def test_skips_when_the_settings_table_doesnt_exist_yet(self):
        # `migrate <app>` on a fresh DB sends post_migrate for every app, alarm included, before the alarm
        # migrations ran. The query used to fail there (InvalidCursorName on Postgres). The rename rolls back with
        # the test's transaction.
        table = AlarmSettingsEntry._meta.db_table
        quote = connection.ops.quote_name
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {quote(table)} RENAME TO {quote(table + '_not_yet')}")

        _post_migrate()

    def test_passes_with_the_key_that_encrypted_the_values(self):
        self._store_encrypted_mqtt_password()

        _post_migrate()

    def test_still_fails_on_a_key_that_cant_decrypt(self):
        self._store_encrypted_mqtt_password()
        self._use_key(Fernet.generate_key().decode())

        with self.assertRaisesMessage(RuntimeError, "SETTINGS_ENCRYPTION_KEY cannot decrypt existing values"):
            _post_migrate()
