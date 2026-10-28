from __future__ import annotations

import threading
from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from accounts.models import Role, User, UserRoleAssignment
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import EncryptionTestMixin
from integrations_home_assistant import state_stream
from integrations_home_assistant.connection import get_cached_connection
from integrations_home_assistant.state_stream import HomeAssistantStateStream, _RuntimeSettings
from integrations_home_assistant.tests.stream_test_utils import FakeSessionStream, run_app_ready


class HomeAssistantEntitiesApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha-entities@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def test_entities_endpoint_requires_auth(self):
        client = APIClient()
        url = reverse("ha-entities")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_entities_endpoint_returns_error_when_not_configured(self):
        url = reverse("ha-entities")
        response = self.client.get(url)
        # Returns 400 (not configured) or 503 (not reachable) depending on gateway state
        self.assertIn(response.status_code, [400, 503])
        self.assertIn("error", response.json())

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_entities_endpoint_returns_list_when_configured(self, mock_gateway):
        mock_gateway.ensure_available.return_value = None
        mock_gateway.list_entities.return_value = [
            {"entity_id": "binary_sensor.front_door", "state": "off"},
            {"entity_id": "light.living_room", "state": "on"},
        ]

        url = reverse("ha-entities")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(len(body["data"]), 2)


class HomeAssistantNotifyServicesApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha-notify@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def test_notify_services_requires_auth(self):
        client = APIClient()
        url = reverse("ha-notify-services")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_notify_services_returns_error_when_not_configured(self):
        url = reverse("ha-notify-services")
        response = self.client.get(url)
        # Returns 400 (not configured) or 503 (not reachable) depending on gateway state
        self.assertIn(response.status_code, [400, 503])
        self.assertIn("error", response.json())

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_notify_services_returns_list_when_configured(self, mock_gateway):
        mock_gateway.ensure_available.return_value = None
        mock_gateway.list_notify_services.return_value = [
            "notify.notify",
            "notify.mobile_app_phone",
        ]

        url = reverse("ha-notify-services")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(len(body["data"]), 2)


class HomeAssistantServicesApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha-services@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def test_services_requires_auth(self):
        client = APIClient()
        url = reverse("ha-service-catalog")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_services_returns_error_when_not_configured(self):
        url = reverse("ha-service-catalog")
        response = self.client.get(url)
        # Returns 400 (not configured) or 503 (not reachable) depending on gateway state
        self.assertIn(response.status_code, [400, 503])
        self.assertIn("error", response.json())

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_services_returns_catalog_when_configured(self, mock_gateway):
        mock_gateway.ensure_available.return_value = None
        mock_gateway.list_service_catalog.return_value = [
            {
                "domain": "light",
                "service": "turn_on",
                "name": "Turn on",
                "description": "",
                "fields": {"rgb_color": {"selector": {"color_rgb": None}}},
            },
        ]

        url = reverse("ha-service-catalog")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"][0]["service"], "turn_on")

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_services_returns_503_when_fetch_fails(self, mock_gateway):
        mock_gateway.ensure_available.return_value = None
        mock_gateway.list_service_catalog.side_effect = RuntimeError("boom")

        url = reverse("ha-service-catalog")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.json())


class HomeAssistantSettingsApiPermissionTests(EncryptionTestMixin, APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha-settings-user@example.com", password="pass")
        self.admin = User.objects.create_user(email="ha-settings-admin@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.admin, role=role)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def test_get_settings_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("ha-settings")
        response = client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_patch_settings_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("ha-settings")
        response = client.patch(url, data={"enabled": True}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_get_settings(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        url = reverse("ha-settings")
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("data", response.json())

    def test_patch_settings_accepts_operational_settings(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        url = reverse("ha-settings")
        response = client.patch(url, data={"connect_timeout_seconds": 5}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_patch_settings_reapplies_state_stream_settings(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        url = reverse("ha-settings")
        stream = HomeAssistantStateStream()
        with (
            patch.object(state_stream, "_stream", stream),
            patch.object(stream, "restart") as restart,
        ):
            # The PATCH relies on the app's `settings_profile_changed` handler to reapply (#120).
            run_app_ready(self)
            with self.captureOnCommitCallbacks(execute=True):
                response = client.patch(
                    url,
                    data={"enabled": True, "base_url": "http://ha-new:8123", "token": "new-token"},
                    format="json",
                )
            self.assertTrue(stream.wait_for_background_apply(timeout=5))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            stream._settings, _RuntimeSettings(enabled=True, base_url="http://ha-new:8123", token="new-token")
        )
        self.assertEqual(get_cached_connection().token, "new-token")
        restart.assert_called_once_with()


class _BlockingCloseWebSocket:
    """A live session whose ``close()`` blocks, like HA not answering the close frame (up to 3s for real)."""

    def __init__(self):
        self.close_entered = threading.Event()
        self.close_returned = threading.Event()
        self.release = threading.Event()

    def close(self) -> None:
        self.close_entered.set()
        self.release.wait(timeout=5)
        self.close_returned.set()


class HomeAssistantSettingsPatchDoesNotBlockTests(EncryptionTestMixin, APITransactionTestCase):
    """The PATCH must not wait on ``stop()``'s close or ``restart()``'s join (#121).

    A transaction test case, so the on-commit hooks run inside the request like they do in production.
    """

    def setUp(self):
        self.admin = User.objects.create_user(email="ha-settings-admin@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.admin, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.fake = FakeSessionStream(self)
        self.stream = self.fake.stream

    def test_patch_returns_while_the_old_session_is_still_closing(self):
        response = self.client.patch(
            reverse("ha-settings"),
            data={"enabled": True, "base_url": "http://ha:8123", "token": "token"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        run_app_ready(self)
        old_thread, _, old_token, _ = self.fake.wait_for_session()
        self.assertEqual(old_token, "token")

        ws = _BlockingCloseWebSocket()
        self.addCleanup(ws.release.set)
        with self.stream._lock:
            self.stream._ws_app = ws
        # A long join too, so a PATCH that waited on it would take that long.
        with patch.object(state_stream, "_RESTART_JOIN_TIMEOUT_SECONDS", 5.0):
            response = self.client.patch(
                reverse("ha-settings"),
                data={"base_url": "http://ha-new:8123", "token": "new-token"},
                format="json",
            )

            self.assertEqual(response.status_code, 200)
            # The response is back, and the background apply is still stuck in the old session's close.
            self.assertTrue(ws.close_entered.wait(timeout=5))
            self.assertFalse(ws.close_returned.is_set())
            self.assertIs(self.stream._thread, old_thread)
            self.assertEqual(get_cached_connection().token, "new-token")

            ws.release.set()
            self.assertTrue(self.stream.wait_for_background_apply(timeout=5))

        _, ws_url, token, stop = self.fake.wait_for_session()
        self.assertEqual((ws_url, token), ("ws://ha-new:8123/api/websocket", "new-token"))
        self.assertFalse(stop.is_set())
        self.assertTrue(self.stream._thread.is_alive())
