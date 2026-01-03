from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserCode, UserRoleAssignment
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import set_profile_settings


class ZwavejsApiTests(APITestCase):
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
        set_profile_settings(
            self.profile,
            zwavejs_connection={
                "enabled": True,
                "ws_url": "ws://zwavejs.local:3000",
                "api_token": "supersecret",
                "connect_timeout_seconds": 5,
                "reconnect_min_seconds": 1,
                "reconnect_max_seconds": 30,
            },
        )

    def test_zwavejs_token_is_masked_in_settings_profile_detail(self):
        url = reverse("alarm-settings-profile-detail", args=[self.profile.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        entries = response.json()["data"]["entries"]
        zw_entries = [e for e in entries if e["key"] == "zwavejs_connection"]
        self.assertEqual(len(zw_entries), 1)
        value = zw_entries[0]["value"]
        self.assertNotIn("api_token", value)
        self.assertEqual(value["has_api_token"], True)

    def test_zwavejs_token_is_masked_in_zwavejs_settings_endpoint(self):
        url = reverse("zwavejs-settings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("api_token", body["data"])
        self.assertEqual(body["data"]["has_api_token"], True)

    def test_patch_zwavejs_settings_preserves_token_when_omitted(self):
        url = reverse("zwavejs-settings")
        response = self.client.patch(url, data={"ws_url": "wss://zwavejs2.local:3000"}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("api_token", body["data"])
        self.assertEqual(body["data"]["has_api_token"], True)

    def test_zwavejs_status_endpoint_does_not_connect_during_tests(self):
        url = reverse("zwavejs-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # External integration is disabled during tests by default.
        body = response.json()
        self.assertEqual(body["data"]["connected"], False)
        self.assertIn("disabled during tests", (body["data"].get("last_error") or "").lower())

    def test_zwavejs_entities_sync_requires_enabled(self):
        set_profile_settings(self.profile, zwavejs_connection={"enabled": False, "ws_url": ""})
        url = reverse("zwavejs-entities-sync")
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_zwavejs_set_value_requires_enabled(self):
        set_profile_settings(self.profile, zwavejs_connection={"enabled": False, "ws_url": ""})
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


class ZwavejsNodesApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="zwavejs-nodes@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.user, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            zwavejs_connection={
                "enabled": True,
                "ws_url": "ws://zwavejs.local:3000",
            },
        )

    def test_nodes_returns_400_when_disabled(self):
        set_profile_settings(self.profile, zwavejs_connection={"enabled": False, "ws_url": ""})
        url = reverse("zwavejs-nodes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertIn("disabled", response.json()["error"]["message"].lower())
