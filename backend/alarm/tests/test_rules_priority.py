from __future__ import annotations

from django.test import TestCase

from alarm.models import Entity, Rule, RuleKind
from alarm.rules_engine import run_rules


class RulesPriorityTests(TestCase):
    def setUp(self):
        self.entity = Entity.objects.create(
            entity_id="binary_sensor.test",
            domain="binary_sensor",
            name="Test Sensor",
            last_state="on",
        )

    def test_multiple_matching_rules_all_fire(self):
        """All matching rules should fire, regardless of priority."""
        Rule.objects.create(
            name="Low Priority",
            kind=RuleKind.TRIGGER,
            enabled=True,
            priority=100,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [],
            },
        )
        Rule.objects.create(
            name="High Priority",
            kind=RuleKind.TRIGGER,
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [],
            },
        )
        Rule.objects.create(
            name="Medium Priority",
            kind=RuleKind.TRIGGER,
            enabled=True,
            priority=50,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [],
            },
        )

        result = run_rules()
        self.assertEqual(result.evaluated, 3)
        self.assertEqual(result.fired, 3)

    def test_disabled_rules_not_evaluated(self):
        Rule.objects.create(
            name="Disabled Rule",
            kind=RuleKind.TRIGGER,
            enabled=False,
            priority=1,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [],
            },
        )
        Rule.objects.create(
            name="Enabled Rule",
            kind=RuleKind.TRIGGER,
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [],
            },
        )

        result = run_rules()
        self.assertEqual(result.evaluated, 1)
        self.assertEqual(result.fired, 1)

    def test_non_matching_rule_not_fired(self):
        Rule.objects.create(
            name="Match Rule",
            kind=RuleKind.TRIGGER,
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [],
            },
        )
        Rule.objects.create(
            name="No Match Rule",
            kind=RuleKind.TRIGGER,
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "off"},
                "then": [],
            },
        )

        result = run_rules()
        self.assertEqual(result.evaluated, 2)
        self.assertEqual(result.fired, 1)
