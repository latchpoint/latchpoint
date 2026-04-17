"""Tests for stop_processing behavior in the dispatcher path (ADR 0084: stop_group scoping)."""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from alarm.dispatcher.dispatcher import EntityChangeBatch, RuleDispatcher, invalidate_entity_rule_cache
from alarm.dispatcher.stats import DispatcherStats
from alarm.models import Entity, Rule, RuleEntityRef, RuleKind


class DispatcherStopProcessingTests(TestCase):
    """Tests for _dispatch_batch stop_processing logic scoped by stop_group (ADR 0084)."""

    def setUp(self):
        invalidate_entity_rule_cache()
        self.entity = Entity.objects.create(
            entity_id="binary_sensor.door",
            domain="binary_sensor",
            name="Door Sensor",
            last_state="on",
        )
        self.now = timezone.now()

    def _make_rule(self, name, kind, priority, stop_processing=False, stop_group="", match="on"):
        rule = Rule.objects.create(
            name=name,
            kind=kind,
            enabled=True,
            priority=priority,
            stop_processing=stop_processing,
            stop_group=stop_group,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.door", "equals": match},
                "then": [],
            },
        )
        RuleEntityRef.objects.create(rule=rule, entity=self.entity)
        return rule

    def _make_batch(self):
        return EntityChangeBatch(
            source="test",
            entity_ids={"binary_sensor.door"},
            changed_at=self.now,
        )

    def _dispatch(self, dispatcher=None):
        dispatcher = dispatcher or RuleDispatcher()
        batch = self._make_batch()
        dispatcher._dispatch_batch(batch)
        return dispatcher._stats

    def test_dispatch_stop_processing_blocks_same_group(self):
        """Dispatcher should skip lower-priority rules sharing the same stop_group when stopper fires."""
        self._make_rule("High Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="door-entry")
        self._make_rule("Low Runner", RuleKind.TRIGGER, 1, stop_group="door-entry")

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 1)
        self.assertEqual(stats.rules_stopped, 1)

    def test_dispatch_stop_processing_does_not_block_different_group(self):
        """Dispatcher stop should not cross stop_group boundaries."""
        self._make_rule("Group A Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="group-a")
        self._make_rule("Group B Runner", RuleKind.TRIGGER, 1, stop_group="group-b")

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 2)
        self.assertEqual(stats.rules_stopped, 0)

    def test_dispatch_stop_processing_does_not_block_same_kind_different_group(self):
        """Regression guard: kind equality no longer implies blocking (ADR 0076 behavior removed)."""
        self._make_rule("Trigger Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="group-a")
        # Same kind (TRIGGER) but no shared stop_group — must still fire.
        self._make_rule("Trigger Runner", RuleKind.TRIGGER, 1, stop_group="")

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 2)
        self.assertEqual(stats.rules_stopped, 0)

    def test_dispatch_stop_processing_with_empty_group_is_noop(self):
        """stop_processing=True with empty stop_group must not block anything."""
        # Using stop_group="" for the stopper (invariant is normally enforced by the serializer,
        # but the dispatcher should remain defensive even if a rule slips through via ORM).
        self._make_rule("Empty-group Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="")
        self._make_rule("Runner", RuleKind.TRIGGER, 1, stop_group="")

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 2)
        self.assertEqual(stats.rules_stopped, 0)

    def test_dispatch_stop_processing_false_no_effect(self):
        """Default stop_processing=False should not block any rules, even with shared groups."""
        self._make_rule("High Normal", RuleKind.TRIGGER, 100, stop_processing=False, stop_group="door-entry")
        self._make_rule("Low Normal", RuleKind.TRIGGER, 1, stop_group="door-entry")

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 2)
        self.assertEqual(stats.rules_stopped, 0)

    def test_dispatch_non_matching_stopper_does_not_block(self):
        """A stopper that doesn't match should not block subsequent rules in the same group."""
        self._make_rule(
            "Non-match Stopper",
            RuleKind.TRIGGER,
            100,
            stop_processing=True,
            stop_group="door-entry",
            match="off",
        )
        self._make_rule("Matching Runner", RuleKind.TRIGGER, 1, stop_group="door-entry", match="on")

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 1)
        self.assertEqual(stats.rules_stopped, 0)

    def test_dispatch_multiple_groups_stopped(self):
        """Two distinct groups can be independently stopped."""
        self._make_rule("Group A Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="group-a")
        self._make_rule("Group B Stopper", RuleKind.DISARM, 100, stop_processing=True, stop_group="group-b")
        self._make_rule("Group A Blocked", RuleKind.TRIGGER, 1, stop_group="group-a")
        self._make_rule("Group B Blocked", RuleKind.DISARM, 1, stop_group="group-b")

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 2)
        self.assertEqual(stats.rules_stopped, 2)

    def test_dispatch_chain_of_stoppers_in_same_group(self):
        """Only the highest-priority stopper in a group fires; lower stoppers in the same group are also blocked."""
        self._make_rule("High Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="door-entry")
        self._make_rule("Mid Stopper", RuleKind.TRIGGER, 50, stop_processing=True, stop_group="door-entry")
        self._make_rule("Low Runner", RuleKind.TRIGGER, 1, stop_group="door-entry")

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 1)
        self.assertEqual(stats.rules_stopped, 2)

    def test_dispatch_door_scenario_adr_0084(self):
        """End-to-end scenario from ADR 0084: guest-mode / pet-sitter / door-trigger share a group."""
        # Rules A and B stop processing when they fire; rule C is the fallback that triggers.
        self._make_rule("Guest Mode Notify", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="door-entry")
        self._make_rule("Pet Sitter Notify", RuleKind.TRIGGER, 90, stop_processing=True, stop_group="door-entry")
        self._make_rule("Trigger Countdown", RuleKind.TRIGGER, 10, stop_group="door-entry")

        stats = self._dispatch()
        # Only the highest-priority fires; the other two in the same group are blocked.
        self.assertEqual(stats.rules_fired, 1)
        self.assertEqual(stats.rules_stopped, 2)


class DispatcherStatsStopTests(TestCase):
    """Unit tests for DispatcherStats stop_processing counters."""

    def test_record_stopped_increments(self):
        stats = DispatcherStats()
        stats.record_stopped()
        stats.record_stopped(3)
        self.assertEqual(stats.rules_stopped, 4)

    def test_as_dict_includes_rules_stopped(self):
        stats = DispatcherStats()
        stats.record_stopped(5)
        d = stats.as_dict()
        self.assertEqual(d["rules_stopped"], 5)

    def test_reset_clears_rules_stopped(self):
        stats = DispatcherStats()
        stats.record_stopped(10)
        stats.reset()
        self.assertEqual(stats.rules_stopped, 0)
