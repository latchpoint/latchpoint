from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserRoleAssignment
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import set_profile_settings
from control_panels.models import ControlPanelDevice


class ControlPanelsApiPermissionTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="admin-perms@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.admin, role=role)

        self.regular_user = User.objects.create_user(email="regular@example.com", password="pass")

        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, zwavejs_connection={"enabled": True, "ws_url": "ws://zwavejs.local:3000"})

    def test_list_control_panels_requires_auth(self):
        client = APIClient()
        url = reverse("control-panel-device-list-create")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_list_control_panels_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.regular_user)
        url = reverse("control-panel-device-list-create")
        response = client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_create_control_panel_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.regular_user)
        url = reverse("control-panel-device-list-create")
        payload = {
            "name": "Ring 1",
            "integration_type": "zwavejs",
            "kind": "ring_keypad_v2",
            "enabled": True,
            "external_id": {"home_id": 1, "node_id": 2},
        }
        response = client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 403)


class ControlPanelsApiCrudTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="admin-crud@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.user, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, zwavejs_connection={"enabled": True, "ws_url": "ws://zwavejs.local:3000"})

    def test_list_control_panels(self):
        ControlPanelDevice.objects.create(
            name="Ring 1",
            integration_type="zwavejs",
            kind="ring_keypad_v2",
            enabled=True,
            external_key="zwavejs:1:2",
            external_id={"home_id": 1, "node_id": 2},
        )
        url = reverse("control-panel-device-list-create")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)

    def test_get_control_panel_detail(self):
        device = ControlPanelDevice.objects.create(
            name="Ring Detail",
            integration_type="zwavejs",
            kind="ring_keypad_v2",
            enabled=True,
            external_key="zwavejs:1:10",
            external_id={"home_id": 1, "node_id": 10},
        )
        url = reverse("control-panel-device-detail", args=[device.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["name"], "Ring Detail")

    def test_update_control_panel_name(self):
        device = ControlPanelDevice.objects.create(
            name="Original Name",
            integration_type="zwavejs",
            kind="ring_keypad_v2",
            enabled=True,
            external_key="zwavejs:1:11",
            external_id={"home_id": 1, "node_id": 11},
        )
        url = reverse("control-panel-device-detail", args=[device.id])
        response = self.client.patch(url, data={"name": "Updated Name"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["name"], "Updated Name")
        device.refresh_from_db()
        self.assertEqual(device.name, "Updated Name")

    def test_delete_control_panel(self):
        device = ControlPanelDevice.objects.create(
            name="To Delete",
            integration_type="zwavejs",
            kind="ring_keypad_v2",
            enabled=True,
            external_key="zwavejs:1:12",
            external_id={"home_id": 1, "node_id": 12},
        )
        url = reverse("control-panel-device-detail", args=[device.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(ControlPanelDevice.objects.filter(id=device.id).exists())

    def test_create_control_panel_without_zwavejs_enabled_fails(self):
        # Disable Z-Wave JS
        set_profile_settings(self.profile, zwavejs_connection={"enabled": False, "ws_url": ""})

        url = reverse("control-panel-device-list-create")
        payload = {
            "name": "Ring No ZWave",
            "integration_type": "zwavejs",
            "kind": "ring_keypad_v2",
            "enabled": True,
            "external_id": {"home_id": 1, "node_id": 99},
        }
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Z-Wave JS", response.json()["error"]["message"])


class ControlPanelsApiValidationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="admin-control-panels@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.user, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, zwavejs_connection={"enabled": True, "ws_url": "ws://zwavejs.local:3000"})

    def test_create_rejects_duplicate_external_key(self):
        url = reverse("control-panel-device-list-create")
        payload = {
            "name": "Ring 1",
            "integration_type": "zwavejs",
            "kind": "ring_keypad_v2",
            "enabled": True,
            "external_id": {"home_id": 1, "node_id": 2},
        }
        resp1 = self.client.post(url, data=payload, format="json")
        self.assertEqual(resp1.status_code, 201)

        resp2 = self.client.post(url, data={**payload, "name": "Ring 2"}, format="json")
        self.assertEqual(resp2.status_code, 400)
        errs = (resp2.json().get("error", {}).get("details", {}) or {}).get("non_field_errors") or []
        self.assertTrue(errs)
        self.assertIn("already configured", str(errs[0]).lower())

    def test_patch_rejects_duplicate_external_key(self):
        a = ControlPanelDevice.objects.create(
            name="A",
            integration_type="zwavejs",
            kind="ring_keypad_v2",
            enabled=True,
            external_key="zwavejs:1:2",
            external_id={"home_id": 1, "node_id": 2},
        )
        b = ControlPanelDevice.objects.create(
            name="B",
            integration_type="zwavejs",
            kind="ring_keypad_v2",
            enabled=True,
            external_key="zwavejs:1:3",
            external_id={"home_id": 1, "node_id": 3},
        )

        url = reverse("control-panel-device-detail", args=[b.id])
        resp = self.client.patch(url, data={"external_id": {"home_id": 1, "node_id": 2}}, format="json")
        self.assertEqual(resp.status_code, 400)
        errs = (resp.json().get("error", {}).get("details", {}) or {}).get("non_field_errors") or []
        self.assertTrue(errs)
        self.assertIn("already configured", str(errs[0]).lower())


class ControlPanelsApiTestBeepTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="admin-control-panels-test@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.user, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.device = ControlPanelDevice.objects.create(
            name="Ring",
            integration_type="zwavejs",
            kind="ring_keypad_v2",
            enabled=True,
            external_key="zwavejs:1:2",
            external_id={"home_id": 1, "node_id": 2},
            beep_volume=50,
        )

    def test_patch_rejects_invalid_beep_volume(self):
        url = reverse("control-panel-device-detail", args=[self.device.id])
        resp = self.client.patch(url, data={"beep_volume": 0}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("beep_volume", resp.json()["error"]["details"])

    def test_test_beep_returns_400_when_node_missing(self):
        from unittest.mock import patch

        class _FakeGateway:
            def ensure_connected(self, *, timeout_seconds: float = 5.0) -> None:
                return

            def controller_get_state(self, *, timeout_seconds: float = 5.0) -> dict:
                return {"state": {"nodes": [{"id": 3}]}}

            def set_value(self, **_kwargs) -> None:
                return

        url = reverse("control-panel-device-test", args=[self.device.id])
        with patch("alarm.gateways.zwavejs.default_zwavejs_gateway", _FakeGateway()):
            resp = self.client.post(url, data={}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_test_beep_uses_saved_volume_by_default(self):
        from unittest.mock import patch

        class _FakeGateway:
            def __init__(self) -> None:
                self.last_set_value_kwargs: dict | None = None

            def ensure_connected(self, *, timeout_seconds: float = 5.0) -> None:
                return

            def controller_get_state(self, *, timeout_seconds: float = 5.0) -> dict:
                return {"state": {"nodes": [{"id": 2}]}}

            def set_value(self, **kwargs) -> None:
                self.last_set_value_kwargs = kwargs

        self.device.beep_volume = 77
        self.device.save(update_fields=["beep_volume", "updated_at"])

        fake = _FakeGateway()
        url = reverse("control-panel-device-test", args=[self.device.id])
        with patch("alarm.gateways.zwavejs.default_zwavejs_gateway", fake):
            resp = self.client.post(url, data={}, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(fake.last_set_value_kwargs)
        self.assertEqual(fake.last_set_value_kwargs.get("property_key"), 9)
        self.assertEqual(fake.last_set_value_kwargs.get("property"), 96)
        self.assertEqual(fake.last_set_value_kwargs.get("value"), 77)

    def test_test_beep_returns_200_when_node_present(self):
        from unittest.mock import patch

        class _FakeGateway:
            def ensure_connected(self, *, timeout_seconds: float = 5.0) -> None:
                return

            def controller_get_state(self, *, timeout_seconds: float = 5.0) -> dict:
                return {"state": {"nodes": [{"id": 2}]}}

            def set_value(self, **_kwargs) -> None:
                return

        url = reverse("control-panel-device-test", args=[self.device.id])
        with patch("alarm.gateways.zwavejs.default_zwavejs_gateway", _FakeGateway()):
            resp = self.client.post(url, data={}, format="json")
        self.assertEqual(resp.status_code, 200)
