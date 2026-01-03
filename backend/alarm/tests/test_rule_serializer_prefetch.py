from __future__ import annotations

from django.test import TestCase

from alarm.models import Entity, Rule, RuleEntityRef, RuleKind
from alarm.serializers import RuleSerializer


class TestRuleSerializerPrefetch(TestCase):
    def test_prefetched_rule_serialization_runs_without_queries(self):
        rule = Rule.objects.create(name="Test", kind=RuleKind.TRIGGER, enabled=True, priority=1)
        door = Entity.objects.create(
            entity_id="binary_sensor.door",
            domain="binary_sensor",
            name="Door",
        )
        window = Entity.objects.create(
            entity_id="binary_sensor.window",
            domain="binary_sensor",
            name="Window",
        )
        RuleEntityRef.objects.create(rule=rule, entity=door)
        RuleEntityRef.objects.create(rule=rule, entity=window)

        prefetched = (
            Rule.objects.filter(id=rule.id)
            .prefetch_related("entity_refs__entity")
            .get()
        )
        with self.assertNumQueries(0):
            data = RuleSerializer(prefetched).data

        self.assertEqual(data["entity_ids"], ["binary_sensor.door", "binary_sensor.window"])

    def test_prefetched_rule_list_serialization_runs_without_queries(self):
        first = Rule.objects.create(name="One", kind=RuleKind.TRIGGER, enabled=True, priority=1)
        second = Rule.objects.create(name="Two", kind=RuleKind.TRIGGER, enabled=True, priority=0)
        entity = Entity.objects.create(entity_id="binary_sensor.motion", domain="binary_sensor", name="Motion")
        RuleEntityRef.objects.create(rule=first, entity=entity)
        RuleEntityRef.objects.create(rule=second, entity=entity)

        rules = list(Rule.objects.all().prefetch_related("entity_refs__entity").order_by("-priority", "id"))
        with self.assertNumQueries(0):
            data = RuleSerializer(rules, many=True).data

        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["entity_ids"], ["binary_sensor.motion"])
        self.assertEqual(data[1]["entity_ids"], ["binary_sensor.motion"])

