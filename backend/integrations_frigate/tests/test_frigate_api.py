from __future__ import annotations

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserRoleAssignment
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import set_profile_settings
from integrations_frigate.models import FrigateDetection


class FrigateApiPermissionTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="frigate-user@example.com", password="pass")
        self.admin = User.objects.create_user(email="frigate-admin@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.admin, role=role)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def test_status_requires_auth(self):
        client = APIClient()
        url = reverse("frigate-status")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_status_allows_authenticated_user(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("frigate-status")
        response = client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_settings_get_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("frigate-settings")
        response = client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_settings_patch_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("frigate-settings")
        response = client.patch(url, data={"enabled": True}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_detections_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("frigate-detections")
        response = client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_detection_detail_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("frigate-detection-detail", kwargs={"pk": 1})
        response = client.get(url)
        self.assertEqual(response.status_code, 403)


class FrigateApiStatusTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="frigate-admin2@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.admin, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def test_status_returns_enabled_state(self):
        url = reverse("frigate-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("enabled", body["data"])
        self.assertIn("mqtt", body["data"])

    def test_settings_get_returns_current_config(self):
        url = reverse("frigate-settings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("enabled", body["data"])
        self.assertIn("events_topic", body["data"])

    def test_settings_patch_requires_mqtt_when_enabling(self):
        # MQTT is not enabled by default
        url = reverse("frigate-settings")
        response = self.client.patch(url, data={"enabled": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("MQTT", response.json()["error"]["message"])

    def test_settings_patch_updates_topic(self):
        set_profile_settings(self.profile, mqtt_connection={"enabled": True, "host": "mqtt.local", "port": 1883})
        url = reverse("frigate-settings")
        response = self.client.patch(url, data={"events_topic": "frigate/custom"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["events_topic"], "frigate/custom")

    def test_options_returns_cameras_and_zones(self):
        url = reverse("frigate-options")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("cameras", body["data"])
        self.assertIn("zones_by_camera", body["data"])

    def test_detections_returns_empty_list(self):
        url = reverse("frigate-detections")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json()["data"], list)

    def test_detections_includes_id_field(self):
        detection = FrigateDetection.objects.create(
            provider="frigate",
            event_id="test-event-123",
            label="person",
            camera="backyard",
            zones=["yard"],
            confidence_pct=92.5,
            observed_at=timezone.now(),
            source_topic="frigate/events",
            raw={"type": "new", "after": {"id": "test-event-123", "camera": "backyard"}},
        )
        url = reverse("frigate-detections")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["id"], detection.id)
        self.assertEqual(body["data"][0]["event_id"], "test-event-123")

    def test_detection_detail_returns_full_data(self):
        raw_payload = {
            "type": "update",
            "before": {"id": "test-event-456"},
            "after": {
                "id": "test-event-456",
                "camera": "frontyard",
                "label": "person",
                "top_score": 0.88,
                "entered_zones": ["porch"],
            },
        }
        detection = FrigateDetection.objects.create(
            provider="frigate",
            event_id="test-event-456",
            label="person",
            camera="frontyard",
            zones=["porch"],
            confidence_pct=88.0,
            observed_at=timezone.now(),
            source_topic="frigate/events",
            raw=raw_payload,
        )
        url = reverse("frigate-detection-detail", kwargs={"pk": detection.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["id"], detection.id)
        self.assertEqual(body["data"]["event_id"], "test-event-456")
        self.assertEqual(body["data"]["camera"], "frontyard")
        self.assertEqual(body["data"]["raw"], raw_payload)

    def test_detection_detail_returns_404_for_missing(self):
        url = reverse("frigate-detection-detail", kwargs={"pk": 99999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
