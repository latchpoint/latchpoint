from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from alarm.models import (
    AlarmEvent,
    AlarmEventType,
    Entity,
    Rule,
    RuleEntityRef,
    RuleKind,
    Sensor,
)
from alarm.serializers import SensorSerializer
from alarm.use_cases.sensor_context import sensor_list_serializer_context


class TestSensorContextQueries(TestCase):
    def test_sensor_list_context_is_constant_queries(self):
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
        rule = Rule.objects.create(name="Uses Door", kind=RuleKind.TRIGGER, enabled=True, priority=1)
        entity = Entity.objects.get(entity_id="binary_sensor.front_door")
        RuleEntityRef.objects.create(rule=rule, entity=entity)

        sensors = list(Sensor.objects.all())

        with self.assertNumQueries(3):
            context = sensor_list_serializer_context(
                sensors=sensors,
                prefer_home_assistant_live_state=False,
            )
            SensorSerializer(sensors, many=True, context=context).data

