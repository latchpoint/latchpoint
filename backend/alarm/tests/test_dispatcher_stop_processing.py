"""Tests for stop_processing behavior in the dispatcher path."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from alarm.dispatcher.dispatcher import EntityChangeBatch, RuleDispatcher, invalidate_entity_rule_cache
from alarm.dispatcher.stats import DispatcherStats
from alarm.models import Entity, Rule, RuleEntityRef, RuleKind


class DispatcherStopProcessingTests(TestCase):
    """Tests for _dispatch_batch stop_processing logic."""

    def setUp(self):
        invalidate_entity_rule_cache()
        self.entity = Entity.objects.create(
            entity_id="binary_sensor.door",
            domain="binary_sensor",
            name="Door Sensor",
            last_state="on",
        )
        self.now = timezone.now()

    def _make_rule(self, name, kind, priority, stop_processing=False, match="on"):
        rule = Rule.objects.create(
            name=name,
            kind=kind,
            enabled=True,
            priority=priority,
            stop_processing=stop_processing,
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

    def test_dispatch_stop_processing_skips_lower_priority(self):
        """Dispatcher should skip lower-priority same-kind rules when stopper fires."""
        self._make_rule("High Stopper", RuleKind.TRIGGER, 100, stop_processing=True)
        self._make_rule("Low Runner", RuleKind.TRIGGER, 1)

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 1)
        self.assertEqual(stats.rules_stopped, 1)

    def test_dispatch_stop_processing_does_not_block_different_kind(self):
        """Dispatcher stop should not cross kind boundaries."""
        self._make_rule("Trigger Stopper", RuleKind.TRIGGER, 100, stop_processing=True)
        self._make_rule("Disarm Runner", RuleKind.DISARM, 1)

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 2)
        self.assertEqual(stats.rules_stopped, 0)

    def test_dispatch_stop_processing_false_no_effect(self):
        """Default stop_processing=False should not block any rules."""
        self._make_rule("High Normal", RuleKind.TRIGGER, 100, stop_processing=False)
        self._make_rule("Low Normal", RuleKind.TRIGGER, 1)

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 2)
        self.assertEqual(stats.rules_stopped, 0)

    def test_dispatch_non_matching_stopper_does_not_block(self):
        """A stopper that doesn't match should not block subsequent rules."""
        self._make_rule("Non-match Stopper", RuleKind.TRIGGER, 100, stop_processing=True, match="off")
        self._make_rule("Matching Runner", RuleKind.TRIGGER, 1, match="on")

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 1)
        self.assertEqual(stats.rules_stopped, 0)

    def test_dispatch_multiple_kinds_stopped(self):
        """Both trigger and disarm kinds can be independently stopped."""
        self._make_rule("Trigger Stopper", RuleKind.TRIGGER, 100, stop_processing=True)
        self._make_rule("Disarm Stopper", RuleKind.DISARM, 100, stop_processing=True)
        self._make_rule("Trigger Blocked", RuleKind.TRIGGER, 1)
        self._make_rule("Disarm Blocked", RuleKind.DISARM, 1)

        stats = self._dispatch()
        self.assertEqual(stats.rules_fired, 2)
        self.assertEqual(stats.rules_stopped, 2)

    def test_dispatch_chain_of_stoppers(self):
        """Only the highest-priority stopper fires; lower stoppers are also blocked."""
        self._make_rule("High Stopper", RuleKind.TRIGGER, 100, stop_processing=True)
        self._make_rule("Mid Stopper", RuleKind.TRIGGER, 50, stop_processing=True)
        self._make_rule("Low Runner", RuleKind.TRIGGER, 1)

        stats = self._dispatch()
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
