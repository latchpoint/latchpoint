from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.models import AlarmSettingsEntry
from alarm.tests.settings_test_utils import EncryptionTestMixin
from alarm.use_cases.settings_profile import ensure_active_settings_profile


class SettingsMaskingApiTests(EncryptionTestMixin, APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="masker@example.com", password="pass", is_staff=True)
        self.profile = ensure_active_settings_profile()

    def _client(self) -> APIClient:
        client = APIClient()
        client.force_authenticate(self.admin)
        return client

    def test_active_settings_masks_encrypted_secret(self):
        entry = AlarmSettingsEntry.objects.get(profile=self.profile, key="home_assistant")
        entry.set_value_with_encryption(
            {"enabled": True, "base_url": "http://ha.local:8123", "token": "super-secret-token"}
        )

        resp = self._client().get(reverse("alarm-settings"))
        self.assertEqual(resp.status_code, 200)

        raw = resp.content.decode()
        self.assertNotIn("super-secret-token", raw)
        self.assertNotIn("enc:v1:", raw)

        entries = {e["key"]: e for e in resp.json()["data"]["entries"]}
        ha_value = entries["home_assistant"]["value"]
        self.assertNotIn("token", ha_value)
        self.assertTrue(ha_value["has_token"])

    def test_generic_patch_encrypts_secret_at_rest(self):
        url = reverse("alarm-settings-profile-detail", kwargs={"profile_id": self.profile.id})
        resp = self._client().patch(
            url,
            data={
                "entries": [
                    {
                        "key": "home_assistant",
                        "value": {"enabled": True, "base_url": "http://ha.local:8123", "token": "patched-secret"},
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

        entry = AlarmSettingsEntry.objects.get(profile=self.profile, key="home_assistant")
        self.assertTrue(entry.value["token"].startswith("enc:v1:"))
        self.assertEqual(SettingsEncryption.get().decrypt(entry.value["token"]), "patched-secret")

        # Response must not echo the plaintext secret back.
        self.assertNotIn("patched-secret", resp.content.decode())

    def test_masked_secret_roundtrips_without_clobbering(self):
        entry = AlarmSettingsEntry.objects.get(profile=self.profile, key="home_assistant")
        entry.set_value_with_encryption({"enabled": False, "base_url": "http://ha.local:8123", "token": "keep-me"})

        # The UI reads back has_token (no token) and PATCHes the masked form; the
        # existing secret must be preserved, not wiped.
        url = reverse("alarm-settings-profile-detail", kwargs={"profile_id": self.profile.id})
        resp = self._client().patch(
            url,
            data={
                "entries": [{"key": "home_assistant", "value": {"enabled": True, "base_url": "http://ha.local:8123"}}]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

        entry.refresh_from_db()
        self.assertEqual(SettingsEncryption.get().decrypt(entry.value["token"]), "keep-me")
        self.assertTrue(entry.value["enabled"])
