from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from alarm.models import Entity, Rule, RuleKind, RuleRuntimeState
from alarm.rules_engine import run_rules


class RulesCooldownTests(TestCase):
    def setUp(self):
        self.entity = Entity.objects.create(
            entity_id="binary_sensor.test",
            domain="binary_sensor",
            name="Test Sensor",
            last_state="on",
        )

    def test_rule_with_cooldown_skips_when_in_cooldown(self):
        rule = Rule.objects.create(
            name="Test Cooldown",
            kind=RuleKind.TRIGGER,
            enabled=True,
            priority=1,
            cooldown_seconds=60,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [],
            },
        )
        # Create runtime with recent fire - use correct node_id
        now = timezone.now()
        RuleRuntimeState.objects.create(
            rule=rule,
            node_id="when",  # Must match what ensure_runtime uses
            last_fired_at=now - timedelta(seconds=30),  # Fired 30s ago, cooldown is 60s
        )

        result = run_rules(now=now)
        self.assertEqual(result.fired, 0)
        self.assertEqual(result.skipped_cooldown, 1)

    def test_rule_without_cooldown_always_fires(self):
        Rule.objects.create(
            name="No Cooldown",
            kind=RuleKind.TRIGGER,
            enabled=True,
            priority=1,
            cooldown_seconds=None,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [],
            },
        )

        result1 = run_rules()
        self.assertEqual(result1.fired, 1)

        # Run again immediately: edge-triggered rules should not refire while the
        # condition remains true.
        result2 = run_rules()
        self.assertEqual(result2.fired, 0)

        # False -> true transition should fire again.
        Entity.objects.filter(entity_id="binary_sensor.test").update(last_state="off")
        result3 = run_rules()
        self.assertEqual(result3.fired, 0)

        Entity.objects.filter(entity_id="binary_sensor.test").update(last_state="on")
        result4 = run_rules()
        self.assertEqual(result4.fired, 1)

    def test_cooldown_resets_after_period(self):
        rule = Rule.objects.create(
            name="Test Reset",
            kind=RuleKind.TRIGGER,
            enabled=True,
            priority=1,
            cooldown_seconds=60,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [],
            },
        )
        # Create runtime with old fire
        now = timezone.now()
        RuleRuntimeState.objects.create(
            rule=rule,
            node_id="when",  # Must match what ensure_runtime uses
            last_fired_at=now - timedelta(seconds=120),  # Fired 120s ago, cooldown is 60s
        )

        result = run_rules(now=now)
        self.assertEqual(result.fired, 1)
        self.assertEqual(result.skipped_cooldown, 0)
