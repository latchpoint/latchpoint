from __future__ import annotations

import uuid
from unittest.mock import Mock, patch

from django.urls import NoReverseMatch, reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmSettingsProfile
from notifications.handlers.base import NotificationResult
from notifications.models import NotificationLog, NotificationProvider


class NotificationsApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="notifications@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.filter(name="Default").first()
        if self.profile is None:
            self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        else:
            AlarmSettingsProfile.objects.update(is_active=False)
            self.profile.is_active = True
            self.profile.save(update_fields=["is_active"])

    def _reverse(self, name: str, *args, **kwargs):
        try:
            return reverse(name, args=args, kwargs=kwargs or None)
        except NoReverseMatch:
            return reverse(f"notifications:{name}", args=args, kwargs=kwargs or None)

    def _create_pushbullet_provider(self, *, name: str = "Pushbullet Main") -> NotificationProvider:
        return NotificationProvider.objects.create(
            profile=self.profile,
            name=name,
            provider_type="pushbullet",
            config={"access_token": "o.fake-token"},
            is_enabled=True,
        )

    def test_endpoints_require_authentication(self):
        provider = self._create_pushbullet_provider()
        client = APIClient()

        cases = [
            ("get", self._reverse("provider-list"), {}),
            ("get", self._reverse("provider-detail", pk=provider.id), {}),
            ("post", self._reverse("provider-test", pk=provider.id), {"data": {}, "format": "json"}),
            ("get", self._reverse("provider-types"), {}),
            ("get", self._reverse("log-list"), {}),
            ("get", self._reverse("pushbullet-devices"), {}),
            (
                "post",
                self._reverse("pushbullet-validate-token"),
                {"data": {"access_token": "o.fake"}, "format": "json"},
            ),
            ("get", self._reverse("ha-services"), {}),
            ("post", self._reverse("ha-system-provider-test"), {"data": {}, "format": "json"}),
        ]

        for method, url, kwargs in cases:
            with self.subTest(method=method, url=url):
                response = getattr(client, method)(url, **kwargs)
                self.assertEqual(response.status_code, 401)

    def test_provider_list_returns_providers(self):
        provider = self._create_pushbullet_provider()

        response = self.client.get(self._reverse("provider-list"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["id"], str(provider.id))

    @patch("notifications.serializers.encrypt_config")
    def test_provider_create_and_duplicate_name_error(self, mock_encrypt_config):
        mock_encrypt_config.side_effect = lambda config, _fields: config
        url = self._reverse("provider-list")
        payload = {
            "name": "Pushbullet Created",
            "provider_type": "pushbullet",
            "config": {"access_token": "o.created-token"},
            "is_enabled": True,
        }

        created = self.client.post(url, data=payload, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertIn("data", created.json())
        self.assertEqual(created.json()["data"]["name"], "Pushbullet Created")

        duplicate = self.client.post(url, data=payload, format="json")
        self.assertEqual(duplicate.status_code, 400)
        duplicate_body = duplicate.json()
        self.assertIn("error", duplicate_body)
        self.assertEqual(duplicate_body["error"]["status"], "validation_error")

    def test_provider_detail_returns_provider(self):
        provider = self._create_pushbullet_provider()

        response = self.client.get(self._reverse("provider-detail", pk=provider.id))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["id"], str(provider.id))
        self.assertEqual(body["data"]["provider_type"], "pushbullet")

    def test_provider_detail_returns_not_found_error(self):
        response = self.client.get(self._reverse("provider-detail", pk=uuid.uuid4()))
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["status"], "not_found")

    @patch("notifications.views.get_dispatcher")
    def test_provider_test_returns_dispatcher_result(self, mock_get_dispatcher):
        provider = self._create_pushbullet_provider()
        dispatcher = Mock()
        dispatcher.test_provider.return_value = NotificationResult.ok("sent")
        mock_get_dispatcher.return_value = dispatcher

        response = self.client.post(self._reverse("provider-test", pk=provider.id), data={}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["success"], True)
        self.assertEqual(body["data"]["message"], "sent")

    def test_provider_test_returns_not_found_error(self):
        response = self.client.post(self._reverse("provider-test", pk=uuid.uuid4()), data={}, format="json")
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["status"], "not_found")

    @patch("notifications.views.get_all_handlers_metadata")
    def test_provider_types_returns_metadata(self, mock_get_all_handlers_metadata):
        mock_get_all_handlers_metadata.return_value = [
            {
                "provider_type": "pushbullet",
                "display_name": "Pushbullet",
                "encrypted_fields": ["access_token"],
                "config_schema": {"type": "object", "properties": {}},
            }
        ]

        response = self.client.get(self._reverse("provider-types"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"][0]["provider_type"], "pushbullet")

    def test_log_list_returns_recent_logs(self):
        provider = self._create_pushbullet_provider()
        NotificationLog.objects.create(
            provider=provider,
            provider_name=provider.name,
            provider_type=provider.provider_type,
            status=NotificationLog.Status.SUCCESS,
            message_preview="Alarm triggered",
            error_message="",
            error_code="",
            rule_name="Rule 1",
        )

        response = self.client.get(self._reverse("log-list"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["provider_name"], provider.name)

    def test_pushbullet_devices_returns_validation_error_without_token(self):
        response = self.client.get(self._reverse("pushbullet-devices"))
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["status"], "validation_error")

    @patch("notifications.views.PushbulletHandler.list_devices")
    def test_pushbullet_devices_returns_device_list(self, mock_list_devices):
        mock_list_devices.return_value = [
            {
                "iden": "dev-1",
                "nickname": "Phone",
                "model": "Pixel",
                "type": "android",
                "pushable": True,
            }
        ]

        response = self.client.get(f"{self._reverse('pushbullet-devices')}?access_token=o.fake")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertIn("devices", body["data"])
        self.assertEqual(body["data"]["devices"][0]["iden"], "dev-1")

    @patch("notifications.views.PushbulletHandler.get_user_info")
    def test_pushbullet_validate_token_returns_user(self, mock_get_user_info):
        mock_get_user_info.return_value = {
            "name": "Test User",
            "email_normalized": "test@example.com",
        }

        response = self.client.post(
            self._reverse("pushbullet-validate-token"),
            data={"access_token": "o.fake"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["valid"], True)
        self.assertEqual(body["data"]["user"]["email"], "test@example.com")

    @patch("notifications.views.HomeAssistantHandler.list_available_services")
    def test_ha_services_returns_service_list(self, mock_list_available_services):
        mock_list_available_services.return_value = ["notify.mobile_app_phone", "notify.notify"]

        response = self.client.get(self._reverse("ha-services"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertIn("services", body["data"])
        self.assertEqual(len(body["data"]["services"]), 2)

    @patch("integrations_home_assistant.api.list_notify_services")
    @patch("integrations_home_assistant.api.get_status")
    def test_ha_system_provider_test_success(self, mock_get_status, mock_list_notify_services):
        mock_get_status.return_value = Mock(configured=True, reachable=True)
        mock_list_notify_services.return_value = ["notify.mobile_app_phone"]

        response = self.client.post(self._reverse("ha-system-provider-test"), data={}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["success"], True)
        self.assertIn("connected", body["data"]["message"].lower())

    @patch("integrations_home_assistant.api.get_status")
    def test_ha_system_provider_test_returns_service_unavailable_when_not_configured(self, mock_get_status):
        mock_get_status.return_value = Mock(configured=False, reachable=False)

        response = self.client.post(self._reverse("ha-system-provider-test"), data={}, format="json")
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["status"], "service_unavailable")
