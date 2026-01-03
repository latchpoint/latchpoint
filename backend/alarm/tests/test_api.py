from __future__ import annotations

from unittest.mock import patch
from datetime import timezone as dt_timezone

from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.hashers import make_password
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from accounts.models import UserCode
from alarm.models import AlarmEvent, AlarmEventType, AlarmSettingsProfile, AlarmState, Entity, Rule, Sensor
from alarm.tests.settings_test_utils import set_profile_settings


class AlarmApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="api@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.code_value = "1234"
        self.code = UserCode.objects.create(
            user=self.user,
            code_hash=make_password(self.code_value),
            label="Test Code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=len(self.code_value),
            is_active=True,
        )
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            profile,
            delay_time=5,
            arming_time=5,
            trigger_time=5,
            code_arm_required=True,
        )

    def test_get_state_bootstraps(self):
        url = reverse("alarm-state")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["current_state"], AlarmState.DISARMED)

    def test_arm_requires_valid_state(self):
        url = reverse("alarm-arm")
        response = self.client.post(url, data={"target_state": "invalid"})
        self.assertEqual(response.status_code, 400)

    def test_arm_requires_code_when_configured(self):
        url = reverse("alarm-arm")
        response = self.client.post(url, data={"target_state": AlarmState.ARMED_AWAY})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            AlarmEvent.objects.filter(event_type=AlarmEventType.FAILED_CODE, metadata__action="arm").exists()
        )

    def test_arm_rejects_invalid_code(self):
        url = reverse("alarm-arm")
        response = self.client.post(
            url,
            data={"target_state": AlarmState.ARMED_AWAY, "code": "9999"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertTrue(
            AlarmEvent.objects.filter(event_type=AlarmEventType.FAILED_CODE, metadata__action="arm").exists()
        )

    def test_arm_to_arming(self):
        url = reverse("alarm-arm")
        response = self.client.post(
            url,
            data={"target_state": AlarmState.ARMED_AWAY, "code": self.code_value},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["current_state"], AlarmState.ARMING)
        self.assertTrue(
            AlarmEvent.objects.filter(event_type=AlarmEventType.CODE_USED, metadata__action="arm").exists()
        )

    def test_disarm_requires_code(self):
        url = reverse("alarm-disarm")
        response = self.client.post(url, data={})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            AlarmEvent.objects.filter(event_type=AlarmEventType.FAILED_CODE, metadata__action="disarm").exists()
        )

    def test_disarm_rejects_invalid_code(self):
        url = reverse("alarm-disarm")
        response = self.client.post(url, data={"code": "9999"})
        self.assertEqual(response.status_code, 401)
        self.assertTrue(
            AlarmEvent.objects.filter(event_type=AlarmEventType.FAILED_CODE, metadata__action="disarm").exists()
        )

    def test_temporary_code_not_active_yet_is_rejected(self):
        url = reverse("alarm-disarm")
        self.code.code_type = UserCode.CodeType.TEMPORARY
        self.code.start_at = timezone.now() + timezone.timedelta(hours=1)
        self.code.save(update_fields=["code_type", "start_at"])

        response = self.client.post(url, data={"code": self.code_value})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["message"], "Code is not active yet.")

    def test_temporary_code_day_restriction_is_enforced(self):
        url = reverse("alarm-disarm")
        fixed_now = timezone.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt_timezone.utc)  # Wednesday
        self.user.timezone = "UTC"
        self.user.save(update_fields=["timezone"])
        self.code.code_type = UserCode.CodeType.TEMPORARY
        self.code.days_of_week = 1 << 5  # Saturday only (Mon=0)
        self.code.save(update_fields=["code_type", "days_of_week"])

        with patch("alarm.services.timezone.now", return_value=fixed_now):
            response = self.client.post(url, data={"code": self.code_value})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["message"], "Code is not valid today.")

    def test_temporary_code_time_window_is_enforced(self):
        url = reverse("alarm-disarm")
        fixed_now = timezone.datetime(2025, 1, 1, 7, 0, 0, tzinfo=dt_timezone.utc)
        self.user.timezone = "UTC"
        self.user.save(update_fields=["timezone"])
        self.code.code_type = UserCode.CodeType.TEMPORARY
        self.code.window_start = timezone.datetime(2025, 1, 1, 8, 0, 0, tzinfo=dt_timezone.utc).time()
        self.code.window_end = timezone.datetime(2025, 1, 1, 10, 0, 0, tzinfo=dt_timezone.utc).time()
        self.code.save(update_fields=["code_type", "window_start", "window_end"])

        with patch("alarm.services.timezone.now", return_value=fixed_now):
            response = self.client.post(url, data={"code": self.code_value})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["message"], "Code is not valid at this time.")

    def test_update_sensor(self):
        sensor = Sensor.objects.create(
            name="Front Door",
            entity_id="binary_sensor.front_door",
            is_active=True,
            is_entry_point=True,
        )

        url = reverse("alarm-sensor-detail", args=[sensor.id])
        response = self.client.patch(url, data={"is_entry_point": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["is_entry_point"], False)

        sensor.refresh_from_db()
        self.assertEqual(sensor.is_entry_point, False)

    def test_get_sensor_detail_404_when_missing(self):
        url = reverse("alarm-sensor-detail", args=[99999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_get_sensors_uses_entity_cache_for_current_state(self):
        Sensor.objects.create(
            name="Front Door",
            entity_id="binary_sensor.front_door",
            is_active=True,
            is_entry_point=True,
        )
        Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front Door",
            last_state="off",
        )

        url = reverse("alarm-sensors")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        by_entity_id = {s["entity_id"]: s for s in response.json()["data"]}
        self.assertEqual(by_entity_id["binary_sensor.front_door"]["current_state"], "closed")

    def test_get_sensors_includes_used_in_rules_flag(self):
        Sensor.objects.create(
            name="Front Door",
            entity_id="binary_sensor.front_door",
            is_active=True,
            is_entry_point=True,
        )
        Sensor.objects.create(
            name="Unused Door",
            entity_id="binary_sensor.unused",
            is_active=True,
            is_entry_point=True,
        )

        url = reverse("alarm-rules")
        payload = {
            "name": "Trigger if door open",
            "kind": "trigger",
            "enabled": True,
            "priority": 10,
            "schema_version": 1,
            "definition": {"when": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"}},
            "entity_ids": ["binary_sensor.front_door"],
        }
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 201)

        url = reverse("alarm-sensors")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        by_entity_id = {s["entity_id"]: s for s in response.json()["data"]}
        self.assertEqual(by_entity_id["binary_sensor.front_door"]["used_in_rules"], True)
        self.assertEqual(by_entity_id["binary_sensor.unused"]["used_in_rules"], False)

    @patch("alarm.views.sensors.ha_gateway")
    def test_get_sensors_prefers_home_assistant_live_state(self, mock_gateway):
        class _Status:
            configured = True
            reachable = True

        mock_gateway.get_status.return_value = _Status()
        mock_gateway.list_entities.return_value = [
            {
                "entity_id": "binary_sensor.front_door",
                "state": "on",
                "attributes": {"friendly_name": "Front Door", "device_class": "door"},
                "last_changed": "2025-01-01T00:00:00Z",
            }
        ]

        Sensor.objects.create(
            name="Front Door",
            entity_id="binary_sensor.front_door",
            is_active=True,
            is_entry_point=True,
        )
        Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front Door",
            last_state="off",
        )

        url = reverse("alarm-sensors")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        by_entity_id = {s["entity_id"]: s for s in response.json()["data"]}
        self.assertEqual(by_entity_id["binary_sensor.front_door"]["current_state"], "open")

    def test_rules_crud(self):
        url = reverse("alarm-rules")
        payload = {
            "name": "Trigger if door open",
            "kind": "trigger",
            "enabled": True,
            "priority": 10,
            "schema_version": 1,
            "definition": {"when": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"}},
            "entity_ids": ["binary_sensor.front_door"],
        }
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 201)
        created = response.json()["data"]
        self.assertEqual(created["name"], payload["name"])
        self.assertEqual(created["kind"], payload["kind"])
        self.assertEqual(created["entity_ids"], ["binary_sensor.front_door"])

        self.assertTrue(Rule.objects.filter(id=created["id"]).exists())
        self.assertTrue(Entity.objects.filter(entity_id="binary_sensor.front_door").exists())

        detail_url = reverse("alarm-rule-detail", args=[created["id"]])
        response = self.client.patch(detail_url, data={"enabled": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["enabled"], False)

        response = self.client.delete(detail_url)
        self.assertEqual(response.status_code, 204)

    def test_rule_detail_404_when_missing(self):
        detail_url = reverse("alarm-rule-detail", args=[99999])
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 404)

    def test_rules_run_endpoint_fires_immediate_rule(self):
        AlarmSettingsProfile.objects.all().delete()
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            profile,
            delay_time=5,
            arming_time=0,
            state_overrides={AlarmState.ARMED_AWAY: {"arming_time": 0}},
            trigger_time=5,
            code_arm_required=False,
        )

        Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front door",
            last_state="on",
        )

        Rule.objects.create(
            name="Disarm when door is on",
            kind="disarm",
            enabled=True,
            priority=1,
            schema_version=1,
            cooldown_seconds=None,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"},
                "then": [{"type": "alarm_disarm"}],
            },
        )

        # Put alarm into an armed state so disarm changes something.
        from alarm import services

        services.arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot = services.timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)

        url = reverse("alarm-rules-run")
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body["data"]["evaluated"], 1)
        self.assertGreaterEqual(body["data"]["fired"], 1)

        snapshot = services.get_current_snapshot(process_timers=False)
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

    def test_rules_simulate_endpoint(self):
        Rule.objects.create(
            name="Match door on",
            kind="trigger",
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"},
                "then": [{"type": "alarm_trigger"}],
            },
        )

        url = reverse("alarm-rules-simulate")
        response = self.client.post(
            url,
            data={"entity_states": {"binary_sensor.front_door": "on"}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["summary"]["evaluated"], 1)
        self.assertEqual(body["data"]["summary"]["matched"], 1)
