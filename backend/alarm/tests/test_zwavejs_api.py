from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserCode, UserRoleAssignment
from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.tests.settings_test_utils import EncryptionTestMixin


class ZwavejsApiTests(EncryptionTestMixin, APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="zwavejs@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.user, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.code = UserCode.objects.create(
            user=self.user,
            code_hash=make_password("1234"),
            label="Test Code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )

        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def _set_zwavejs_settings(self, **overrides):
        definition = ALARM_PROFILE_SETTINGS_BY_KEY["zwavejs"]
        entry, _ = AlarmSettingsEntry.objects.get_or_create(
            profile=self.profile,
            key="zwavejs",
            defaults={"value": definition.default, "value_type": definition.value_type},
        )
        entry.set_value_with_encryption(overrides)
        return entry

    def test_zwavejs_token_is_masked_in_zwavejs_settings_endpoint(self):
        self._set_zwavejs_settings(
            enabled=True,
            ws_url="ws://zwavejs.local:3000",
            api_token="supersecret",
        )

        url = reverse("zwavejs-settings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("api_token", body["data"])
        self.assertEqual(body["data"]["has_api_token"], True)

    @patch("integrations_zwavejs.manager.ZwavejsConnectionManager.apply_settings")
    def test_patch_zwavejs_settings_accepts_operational_settings(self, _mock_apply):
        url = reverse("zwavejs-settings")
        response = self.client.patch(url, data={"connect_timeout_seconds": 10}, format="json")
        self.assertEqual(response.status_code, 200)
        _mock_apply.assert_called_once()

    def test_zwavejs_status_endpoint_returns_disconnected_by_default(self):
        url = reverse("zwavejs-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["connected"], False)

    def test_zwavejs_entities_sync_requires_enabled(self):
        # Default entry has enabled=False
        url = reverse("zwavejs-entities-sync")
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_zwavejs_set_value_requires_enabled(self):
        url = reverse("zwavejs-set-value")
        response = self.client.post(
            url,
            data={"node_id": 1, "command_class": 49, "endpoint": 0, "property": "targetValue", "value": True},
            format="json",
        )
        self.assertEqual(response.status_code, 400)


class ZwavejsApiPermissionsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="nonadmin-zwavejs@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_non_admin_cannot_update_zwavejs_settings(self):
        url = reverse("zwavejs-settings")
        response = self.client.patch(url, data={"ws_url": "ws://zwavejs.local:3000"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_test_zwavejs_connection(self):
        url = reverse("zwavejs-test")
        response = self.client.post(url, data={"ws_url": "ws://zwavejs.local:3000"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_sync_zwavejs_entities(self):
        url = reverse("zwavejs-entities-sync")
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_set_zwavejs_value(self):
        url = reverse("zwavejs-set-value")
        response = self.client.post(
            url,
            data={"node_id": 1, "command_class": 49, "endpoint": 0, "property": "targetValue", "value": True},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_list_zwavejs_nodes(self):
        url = reverse("zwavejs-nodes")
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 403)


class ZwavejsNodesApiTests(EncryptionTestMixin, APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="zwavejs-nodes@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.user, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def test_nodes_returns_400_when_disabled(self):
        url = reverse("zwavejs-nodes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertIn("disabled", response.json()["error"]["message"].lower())
