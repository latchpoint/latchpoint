from __future__ import annotations

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmEvent, AlarmEventType, Entity, Sensor


class TestSensorDetailQueries(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="sensor-detail@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_sensor_detail_is_constant_queries(self):
        sensor = Sensor.objects.create(name="Front Door", entity_id="binary_sensor.front_door", is_active=True)
        Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front Door",
            last_state="off",
        )
        AlarmEvent.objects.create(
            event_type=AlarmEventType.SENSOR_TRIGGERED,
            timestamp=timezone.now(),
            sensor=sensor,
            metadata={},
        )

        url = reverse("alarm-sensor-detail", args=[sensor.id])
        with self.assertNumQueries(4):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["entity_id"], "binary_sensor.front_door")
