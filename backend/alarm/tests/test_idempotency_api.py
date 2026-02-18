from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmEvent, AlarmEventType, AlarmSettingsProfile, AlarmState, AlarmStateSnapshot, Entity
from alarm.state_machine import transitions
from alarm.tests.settings_test_utils import set_profile_settings


class IdempotencyApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="idem-user@example.com", password="pass")
        self.admin = User.objects.create_user(email="idem-admin@example.com", password="pass", is_staff=True)

        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)

        AlarmSettingsProfile.objects.update(is_active=False)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            arming_time=30,
            code_arm_required=False,
        )

    def test_cancel_arming_repeated_calls_keep_deterministic_state_without_duplicate_transition(self):
        transitions.disarm(reason="test_setup")
        transitions.arm(target_state=AlarmState.ARMED_AWAY, user=self.user, reason="test_arm")

        url = reverse("alarm-cancel-arming")
        first = self.client.post(url, data={}, format="json")
        second = self.client.post(url, data={}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["status"], "conflict")

        snapshot = AlarmStateSnapshot.objects.first()
        assert snapshot is not None
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

        disarmed_events = AlarmEvent.objects.filter(
            event_type=AlarmEventType.DISARMED,
            state_to=AlarmState.DISARMED,
        )
        self.assertEqual(disarmed_events.count(), 1)

    def test_activate_profile_repeated_calls_keep_only_one_active_profile(self):
        AlarmSettingsProfile.objects.all().delete()
        active_profile = AlarmSettingsProfile.objects.create(name="Active", is_active=True)
        candidate = AlarmSettingsProfile.objects.create(name="Candidate", is_active=False)

        url = reverse("alarm-settings-profile-activate", kwargs={"profile_id": candidate.id})
        first = self.admin_client.post(url, data={}, format="json")
        second = self.admin_client.post(url, data={}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        active_ids = list(
            AlarmSettingsProfile.objects.filter(is_active=True).values_list("id", flat=True)
        )
        self.assertEqual(active_ids, [candidate.id])

        active_profile.refresh_from_db()
        candidate.refresh_from_db()
        self.assertEqual(active_profile.is_active, False)
        self.assertEqual(candidate.is_active, True)

    @patch("alarm.views.entities.ha_gateway")
    def test_entity_sync_repeated_calls_are_idempotent_for_entity_upserts(self, mock_gateway):
        mock_gateway.ensure_available.return_value = None
        mock_gateway.list_entities.return_value = [
            {
                "entity_id": "binary_sensor.front_door",
                "state": "off",
                "name": "Front Door",
                "domain": "binary_sensor",
            }
        ]

        url = reverse("alarm-entities-sync")
        first = self.client.post(url, data={}, format="json")
        second = self.client.post(url, data={}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["data"]["imported"], 1)
        self.assertEqual(first.json()["data"]["updated"], 0)
        self.assertEqual(second.json()["data"]["imported"], 0)
        self.assertEqual(second.json()["data"]["updated"], 1)

        self.assertEqual(Entity.objects.count(), 1)
