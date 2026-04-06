from __future__ import annotations

from django.test import TestCase

from alarm.models import Entity, Rule, RuleKind
from alarm.rules_engine import run_rules, simulate_rules


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


class StopProcessingTests(TestCase):
    def setUp(self):
        self.entity = Entity.objects.create(
            entity_id="binary_sensor.test",
            domain="binary_sensor",
            name="Test Sensor",
            last_state="on",
        )

    def _make_rule(self, name, kind, priority, stop_processing=False, match="on"):
        return Rule.objects.create(
            name=name,
            kind=kind,
            enabled=True,
            priority=priority,
            stop_processing=stop_processing,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": match},
                "then": [],
            },
        )

    def test_stop_processing_skips_lower_priority_same_kind(self):
        """A rule with stop_processing=True should prevent lower-priority same-kind rules from firing."""
        self._make_rule("High Stopper", RuleKind.TRIGGER, 100, stop_processing=True)
        self._make_rule("Low Runner", RuleKind.TRIGGER, 1)

        result = run_rules()
        self.assertEqual(result.fired, 1)
        self.assertEqual(result.skipped_stopped, 1)
        self.assertEqual(result.evaluated, 1)

    def test_stop_processing_does_not_block_different_kind(self):
        """A trigger rule with stop_processing should not block disarm rules."""
        self._make_rule("Trigger Stopper", RuleKind.TRIGGER, 100, stop_processing=True)
        self._make_rule("Disarm Runner", RuleKind.DISARM, 1)

        result = run_rules()
        self.assertEqual(result.fired, 2)
        self.assertEqual(result.skipped_stopped, 0)

    def test_stop_processing_false_does_not_skip(self):
        """Default stop_processing=False preserves fire-all behavior."""
        self._make_rule("High Normal", RuleKind.TRIGGER, 100, stop_processing=False)
        self._make_rule("Low Normal", RuleKind.TRIGGER, 1)

        result = run_rules()
        self.assertEqual(result.fired, 2)
        self.assertEqual(result.skipped_stopped, 0)

    def test_stop_processing_non_matching_rule_does_not_stop(self):
        """A stop_processing rule that doesn't match should not block subsequent rules."""
        self._make_rule("Non-match Stopper", RuleKind.TRIGGER, 100, stop_processing=True, match="off")
        self._make_rule("Matching Runner", RuleKind.TRIGGER, 1, match="on")

        result = run_rules()
        self.assertEqual(result.fired, 1)
        self.assertEqual(result.skipped_stopped, 0)

    def test_simulate_shows_blocked_rules(self):
        """Simulation should annotate rules blocked by stop_processing."""
        stopper = self._make_rule("High Stopper", RuleKind.TRIGGER, 100, stop_processing=True)
        blocked = self._make_rule("Low Blocked", RuleKind.TRIGGER, 1)

        result = simulate_rules(entity_states={"binary_sensor.test": "on"})

        self.assertEqual(result["summary"]["blocked"], 1)
        self.assertEqual(result["summary"]["matched"], 1)

        # The blocked rule should be in non_matching_rules with annotations
        non_matching = result["non_matching_rules"]
        blocked_entries = [r for r in non_matching if r.get("blocked_by_stop_processing")]
        self.assertEqual(len(blocked_entries), 1)
        self.assertEqual(blocked_entries[0]["id"], blocked.id)
        self.assertEqual(blocked_entries[0]["blocked_by_rule_id"], stopper.id)

    def test_multiple_matching_rules_all_fire_still_passes(self):
        """Regression: rules without stop_processing should all fire as before."""
        self._make_rule("Rule A", RuleKind.TRIGGER, 100)
        self._make_rule("Rule B", RuleKind.TRIGGER, 50)
        self._make_rule("Rule C", RuleKind.TRIGGER, 1)

        result = run_rules()
        self.assertEqual(result.evaluated, 3)
        self.assertEqual(result.fired, 3)
        self.assertEqual(result.skipped_stopped, 0)
