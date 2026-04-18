from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from alarm.models import Entity, Rule, RuleKind, RuleRuntimeState
from alarm.rules_engine import RuleRunResult, run_rules, simulate_rules


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

    def _make_rule(self, name, kind, priority, stop_processing=False, stop_group="", match="on"):
        return Rule.objects.create(
            name=name,
            kind=kind,
            enabled=True,
            priority=priority,
            stop_processing=stop_processing,
            stop_group=stop_group,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": match},
                "then": [],
            },
        )

    def test_stop_processing_skips_lower_priority_same_group(self):
        """A rule with stop_processing=True should prevent lower-priority rules in the same stop_group from firing."""
        self._make_rule("High Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")
        self._make_rule("Low Runner", RuleKind.TRIGGER, 1, stop_group="g")

        result = run_rules()
        self.assertEqual(result.fired, 1)
        self.assertEqual(result.skipped_stopped, 1)
        self.assertEqual(result.evaluated, 1)

    def test_stop_processing_does_not_block_different_group(self):
        """A stopper in group A should not block a rule in group B, regardless of kind."""
        self._make_rule("Group A Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="a")
        self._make_rule("Group B Runner", RuleKind.DISARM, 1, stop_group="b")

        result = run_rules()
        self.assertEqual(result.fired, 2)
        self.assertEqual(result.skipped_stopped, 0)

    def test_stop_processing_same_kind_no_shared_group_does_not_block(self):
        """Regression for ADR 0084: same kind alone no longer implies blocking."""
        self._make_rule("Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="a")
        # Same kind but different (empty) group — must still fire.
        self._make_rule("Runner", RuleKind.TRIGGER, 1, stop_group="")

        result = run_rules()
        self.assertEqual(result.fired, 2)
        self.assertEqual(result.skipped_stopped, 0)

    def test_stop_processing_false_does_not_skip(self):
        """Default stop_processing=False preserves fire-all behavior, even with shared group."""
        self._make_rule("High Normal", RuleKind.TRIGGER, 100, stop_processing=False, stop_group="g")
        self._make_rule("Low Normal", RuleKind.TRIGGER, 1, stop_group="g")

        result = run_rules()
        self.assertEqual(result.fired, 2)
        self.assertEqual(result.skipped_stopped, 0)

    def test_stop_processing_non_matching_rule_does_not_stop(self):
        """A stop_processing rule that doesn't match should not block subsequent rules."""
        self._make_rule("Non-match Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g", match="off")
        self._make_rule("Matching Runner", RuleKind.TRIGGER, 1, stop_group="g", match="on")

        result = run_rules()
        self.assertEqual(result.fired, 1)
        self.assertEqual(result.skipped_stopped, 0)

    def test_simulate_shows_blocked_rules(self):
        """Simulation should annotate rules blocked by stop_processing, including stop_group name."""
        stopper = self._make_rule("High Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")
        blocked = self._make_rule("Low Blocked", RuleKind.TRIGGER, 1, stop_group="g")

        result = simulate_rules(entity_states={"binary_sensor.test": "on"})

        self.assertEqual(result["summary"]["blocked"], 1)
        self.assertEqual(result["summary"]["matched"], 1)

        # The blocked rule should be in non_matching_rules with annotations
        non_matching = result["non_matching_rules"]
        blocked_entries = [r for r in non_matching if r.get("blocked_by_stop_processing")]
        self.assertEqual(len(blocked_entries), 1)
        self.assertEqual(blocked_entries[0]["id"], blocked.id)
        self.assertEqual(blocked_entries[0]["blocked_by_rule_id"], stopper.id)
        self.assertEqual(blocked_entries[0]["blocked_by_stop_group"], "g")

    def test_multiple_matching_rules_all_fire_still_passes(self):
        """Regression: rules without stop_processing should all fire as before."""
        self._make_rule("Rule A", RuleKind.TRIGGER, 100)
        self._make_rule("Rule B", RuleKind.TRIGGER, 50)
        self._make_rule("Rule C", RuleKind.TRIGGER, 1)

        result = run_rules()
        self.assertEqual(result.evaluated, 3)
        self.assertEqual(result.fired, 3)
        self.assertEqual(result.skipped_stopped, 0)

    # --- Empty-group defense ---

    def test_stop_processing_with_empty_group_is_noop(self):
        """stop_processing=True with empty stop_group must not block anything (engine defense)."""
        self._make_rule("Empty-group Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="")
        self._make_rule("Runner", RuleKind.TRIGGER, 1, stop_group="")

        result = run_rules()
        self.assertEqual(result.fired, 2)
        self.assertEqual(result.skipped_stopped, 0)

    # --- Same-priority tiebreaking ---

    def test_stop_processing_same_priority_lower_id_wins(self):
        """When two stop_processing rules in the same group have the same priority, the lower ID fires first."""
        first = self._make_rule("First Created", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")
        second = self._make_rule("Second Created", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")
        self.assertLess(first.id, second.id)

        result = run_rules()
        # Only the first (lower id) fires; the second is stopped
        self.assertEqual(result.fired, 1)
        self.assertEqual(result.skipped_stopped, 1)

    # --- Multiple groups stopped simultaneously ---

    def test_stop_processing_multiple_groups_stopped(self):
        """Two distinct groups can be independently stopped."""
        self._make_rule("Group A Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="a")
        self._make_rule("Group B Stopper", RuleKind.DISARM, 100, stop_processing=True, stop_group="b")
        self._make_rule("Group A Blocked", RuleKind.TRIGGER, 1, stop_group="a")
        self._make_rule("Group B Blocked", RuleKind.DISARM, 1, stop_group="b")

        result = run_rules()
        self.assertEqual(result.fired, 2)  # Both stoppers fire
        self.assertEqual(result.skipped_stopped, 2)  # Both lower-priority rules blocked
        self.assertEqual(result.evaluated, 2)  # Only the stoppers were evaluated

    def test_stop_processing_only_blocks_same_group_across_many_groups(self):
        """With multiple groups in play, stop only blocks the matching group."""
        self._make_rule("Group A Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="a")
        self._make_rule("Group B Runner", RuleKind.DISARM, 50, stop_group="b")
        self._make_rule("Group C Runner", RuleKind.ARM, 50, stop_group="c")
        self._make_rule("Group A Blocked", RuleKind.TRIGGER, 1, stop_group="a")

        result = run_rules()
        self.assertEqual(result.fired, 3)  # Stopper + group-b + group-c
        self.assertEqual(result.skipped_stopped, 1)  # Only group-a blocked
        self.assertEqual(result.evaluated, 3)

    # --- Audit trace verification ---

    def test_stop_processing_trace_includes_flag(self):
        """When a stop_processing rule fires, the trace should include stop_processing: True."""
        traces = []

        def capture_log(*, rule, fired_at, kind, actions, result, trace, error=None):
            traces.append(trace)

        self._make_rule("Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")

        run_rules(log_action_func=capture_log)
        self.assertEqual(len(traces), 1)
        self.assertTrue(traces[0].get("stop_processing"))

    def test_normal_rule_trace_omits_stop_flag(self):
        """When a normal rule fires, the trace should NOT include stop_processing."""
        traces = []

        def capture_log(*, rule, fired_at, kind, actions, result, trace, error=None):
            traces.append(trace)

        self._make_rule("Normal", RuleKind.TRIGGER, 100, stop_processing=False)

        run_rules(log_action_func=capture_log)
        self.assertEqual(len(traces), 1)
        self.assertNotIn("stop_processing", traces[0])

    # --- RuleRunResult.as_dict() ---

    def test_rule_run_result_as_dict_includes_skipped_stopped(self):
        """RuleRunResult.as_dict() should include skipped_stopped."""
        result = RuleRunResult(evaluated=5, fired=2, scheduled=1, skipped_cooldown=0, skipped_stopped=3, errors=0)
        d = result.as_dict()
        self.assertEqual(d["skipped_stopped"], 3)
        self.assertEqual(d["evaluated"], 5)

    # --- Chain of stoppers ---

    def test_first_stopper_wins_subsequent_stoppers_blocked(self):
        """If multiple same-group rules have stop_processing, only the highest-priority one fires."""
        self._make_rule("High Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")
        self._make_rule("Mid Stopper", RuleKind.TRIGGER, 50, stop_processing=True, stop_group="g")
        self._make_rule("Low Runner", RuleKind.TRIGGER, 1, stop_group="g")

        result = run_rules()
        self.assertEqual(result.fired, 1)  # Only high stopper
        self.assertEqual(result.skipped_stopped, 2)  # Mid stopper + low runner

    # --- Stopper that doesn't match leaves subsequent stoppers intact ---

    def test_non_matching_stopper_allows_lower_stopper_to_fire(self):
        """If a high-priority stopper doesn't match, a lower-priority stopper can still fire and stop."""
        self._make_rule("High Non-match", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g", match="off")
        self._make_rule("Mid Stopper", RuleKind.TRIGGER, 50, stop_processing=True, stop_group="g")
        self._make_rule("Low Runner", RuleKind.TRIGGER, 1, stop_group="g")

        result = run_rules()
        self.assertEqual(result.fired, 1)  # Only mid stopper
        self.assertEqual(result.skipped_stopped, 1)  # Low runner blocked
        self.assertEqual(result.evaluated, 2)  # High (non-match) + mid evaluated


class StopProcessingTimerTests(TestCase):
    """Tests for stop_processing interaction with timer (for-condition) rules."""

    def setUp(self):
        self.entity = Entity.objects.create(
            entity_id="binary_sensor.test",
            domain="binary_sensor",
            name="Test Sensor",
            last_state="on",
        )
        self.now = timezone.now()

    def _make_for_rule(self, name, kind, priority, for_seconds, stop_processing=False, stop_group="", match="on"):
        """Create a rule with a 'for' duration condition."""
        return Rule.objects.create(
            name=name,
            kind=kind,
            enabled=True,
            priority=priority,
            stop_processing=stop_processing,
            stop_group=stop_group,
            schema_version=1,
            definition={
                "when": {
                    "op": "for",
                    "seconds": for_seconds,
                    "child": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": match},
                },
                "then": [],
            },
        )

    def _make_immediate_rule(self, name, kind, priority, stop_processing=False, stop_group="", match="on"):
        """Create a non-timer rule."""
        return Rule.objects.create(
            name=name,
            kind=kind,
            enabled=True,
            priority=priority,
            stop_processing=stop_processing,
            stop_group=stop_group,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": match},
                "then": [],
            },
        )

    def _make_runtime_due(self, rule, became_true_at=None, scheduled_for=None):
        """Create a RuleRuntimeState that's due to fire."""
        became = became_true_at or (self.now - timedelta(seconds=120))
        sched = scheduled_for or (self.now - timedelta(seconds=1))
        return RuleRuntimeState.objects.create(
            rule=rule,
            node_id="when",
            status="pending",
            became_true_at=became,
            scheduled_for=sched,
        )

    def test_timer_stopper_blocks_same_group_immediate_rule(self):
        """A timer rule with stop_processing that fires should block immediate rules in the same stop_group."""
        timer_rule = self._make_for_rule(
            "Timer Stopper", RuleKind.TRIGGER, 100, 60, stop_processing=True, stop_group="g"
        )
        self._make_runtime_due(timer_rule)
        self._make_immediate_rule("Immediate Runner", RuleKind.TRIGGER, 1, stop_group="g")

        result = run_rules(now=self.now)
        self.assertEqual(result.fired, 1)
        self.assertEqual(result.skipped_stopped, 1)
        # evaluated = len(rules) - skipped_stopped. Both rules are in rules list.
        self.assertEqual(result.evaluated, 1)

    def test_timer_stopper_does_not_block_different_group(self):
        """A timer rule with stop_processing only blocks rules in the same stop_group."""
        timer_rule = self._make_for_rule(
            "Timer Stopper", RuleKind.TRIGGER, 100, 60, stop_processing=True, stop_group="a"
        )
        self._make_runtime_due(timer_rule)
        self._make_immediate_rule("Different-group Runner", RuleKind.DISARM, 1, stop_group="b")

        result = run_rules(now=self.now)
        self.assertEqual(result.fired, 2)
        self.assertEqual(result.skipped_stopped, 0)

    def test_timer_stopper_blocks_another_due_timer(self):
        """A timer rule with stop_processing should prevent a lower-priority due timer in the same group from firing."""
        timer_a = self._make_for_rule(
            "High Timer Stopper", RuleKind.TRIGGER, 100, 60, stop_processing=True, stop_group="g"
        )
        timer_b = self._make_for_rule("Low Timer Runner", RuleKind.TRIGGER, 1, 60, stop_group="g")
        self._make_runtime_due(timer_a)
        self._make_runtime_due(timer_b)

        result = run_rules(now=self.now)
        self.assertEqual(result.fired, 1)  # Only the high-priority timer fires

    def test_timer_stopper_evaluated_count_correct(self):
        """Counters should be correct when a timer stopper fires and blocks same-group immediate rules."""
        timer_rule = self._make_for_rule(
            "Timer Stopper", RuleKind.TRIGGER, 100, 60, stop_processing=True, stop_group="g"
        )
        self._make_runtime_due(timer_rule)
        self._make_immediate_rule("Blocked A", RuleKind.TRIGGER, 50, stop_group="g")
        self._make_immediate_rule("Blocked B", RuleKind.TRIGGER, 1, stop_group="g")
        self._make_immediate_rule("Different Group OK", RuleKind.DISARM, 1, stop_group="other")

        result = run_rules(now=self.now)
        self.assertEqual(result.fired, 2)  # Timer stopper + different-group rule
        self.assertEqual(result.skipped_stopped, 2)  # Blocked A + Blocked B
        # evaluated = len(rules=4) - skipped_stopped(2) = 2
        self.assertEqual(result.evaluated, 2)

    def test_immediate_stopper_blocks_lower_priority_due_timer(self):
        """A high-priority immediate stopper should block a lower-priority due timer in the same group."""
        self._make_immediate_rule("Immediate Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")
        timer_rule = self._make_for_rule("Low Timer", RuleKind.TRIGGER, 1, 60, stop_group="g")
        self._make_runtime_due(timer_rule)

        result = run_rules(now=self.now)
        self.assertEqual(result.fired, 1)  # Only the immediate stopper
        self.assertEqual(result.skipped_stopped, 1)  # Timer blocked

    def test_timer_priority_wins_over_chronological_order(self):
        """A higher-priority timer stopper should block a lower-priority same-group timer even if due later."""
        timer_low = self._make_for_rule("Low Timer", RuleKind.TRIGGER, 1, 60, stop_group="g")
        timer_high = self._make_for_rule(
            "High Timer Stopper", RuleKind.TRIGGER, 100, 60, stop_processing=True, stop_group="g"
        )
        # Low-priority timer is due earlier (chronologically first)
        self._make_runtime_due(timer_low, scheduled_for=self.now - timedelta(seconds=10))
        self._make_runtime_due(timer_high, scheduled_for=self.now - timedelta(seconds=1))

        result = run_rules(now=self.now)
        self.assertEqual(result.fired, 1)  # Only the high-priority stopper
        self.assertEqual(result.skipped_stopped, 1)  # Low timer blocked


class StopProcessingSimulationTests(TestCase):
    """Comprehensive tests for stop_processing in simulate_rules()."""

    def setUp(self):
        self.entity = Entity.objects.create(
            entity_id="binary_sensor.test",
            domain="binary_sensor",
            name="Test Sensor",
            last_state="on",
        )

    def _make_rule(self, name, kind, priority, stop_processing=False, stop_group="", match="on", for_seconds=None):
        definition = {
            "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": match},
            "then": [{"action": "test_action"}],
        }
        if for_seconds:
            definition["when"] = {
                "op": "for",
                "seconds": for_seconds,
                "child": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": match},
            }
        return Rule.objects.create(
            name=name,
            kind=kind,
            enabled=True,
            priority=priority,
            stop_processing=stop_processing,
            stop_group=stop_group,
            schema_version=1,
            definition=definition,
        )

    def test_simulate_evaluated_excludes_blocked(self):
        """Simulation evaluated count should exclude blocked rules (consistent with run_rules)."""
        self._make_rule("Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")
        self._make_rule("Blocked", RuleKind.TRIGGER, 1, stop_group="g")

        result = simulate_rules(entity_states={"binary_sensor.test": "on"})
        self.assertEqual(result["summary"]["evaluated"], 1)
        self.assertEqual(result["summary"]["blocked"], 1)
        self.assertEqual(result["summary"]["matched"], 1)

    def test_simulate_non_matching_stopper_does_not_block(self):
        """A stopper that doesn't match should not block other rules in simulation."""
        self._make_rule("Non-match Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g", match="off")
        runner = self._make_rule("Runner", RuleKind.TRIGGER, 1, stop_group="g")

        result = simulate_rules(entity_states={"binary_sensor.test": "on"})
        self.assertEqual(result["summary"]["blocked"], 0)
        self.assertEqual(result["summary"]["matched"], 1)
        matched_ids = [r["id"] for r in result["matched_rules"] if r["matched"]]
        self.assertIn(runner.id, matched_ids)

    def test_simulate_multiple_groups_blocked(self):
        """Simulation should track blocked rules per-group independently."""
        self._make_rule("Group A Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="a")
        self._make_rule("Group B Stopper", RuleKind.DISARM, 100, stop_processing=True, stop_group="b")
        self._make_rule("Group A Blocked", RuleKind.TRIGGER, 1, stop_group="a")
        self._make_rule("Group B Blocked", RuleKind.DISARM, 1, stop_group="b")
        self._make_rule("Ungrouped Runner", RuleKind.ARM, 1, stop_group="")

        result = simulate_rules(entity_states={"binary_sensor.test": "on"})
        self.assertEqual(result["summary"]["blocked"], 2)
        self.assertEqual(result["summary"]["matched"], 3)  # 2 stoppers + ungrouped runner
        self.assertEqual(result["summary"]["evaluated"], 3)  # 5 total - 2 blocked

    def test_simulate_blocked_rule_has_no_trace(self):
        """Blocked rules should have blocked_by annotations (including stop_group) but no trace."""
        stopper = self._make_rule("Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")
        self._make_rule("Blocked", RuleKind.TRIGGER, 1, stop_group="g")

        result = simulate_rules(entity_states={"binary_sensor.test": "on"})
        blocked_entries = [r for r in result["non_matching_rules"] if r.get("blocked_by_stop_processing")]
        self.assertEqual(len(blocked_entries), 1)
        entry = blocked_entries[0]
        self.assertTrue(entry["blocked_by_stop_processing"])
        self.assertEqual(entry["blocked_by_rule_id"], stopper.id)
        self.assertEqual(entry["blocked_by_stop_group"], "g")
        # Blocked rules don't have trace data since condition was never evaluated
        self.assertNotIn("trace", entry)

    def test_simulate_for_rule_would_schedule_does_not_block(self):
        """A for-rule stopper in 'would_schedule' state has not fired — should NOT block."""
        self._make_rule("For Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g", for_seconds=30)
        runner = self._make_rule("Runner", RuleKind.TRIGGER, 1, stop_group="g")

        # Without assume_for_seconds, the for-rule is "would_schedule" — not yet fired
        result = simulate_rules(entity_states={"binary_sensor.test": "on"})
        self.assertEqual(result["summary"]["blocked"], 0)
        matched_ids = [r["id"] for r in result["matched_rules"]]
        self.assertIn(runner.id, matched_ids)

    def test_simulate_for_rule_stopper_with_assume_for(self):
        """A for-rule stopper with assumed duration should show as fully matched and still block."""
        self._make_rule("For Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g", for_seconds=30)
        self._make_rule("Blocked", RuleKind.TRIGGER, 1, stop_group="g")

        result = simulate_rules(
            entity_states={"binary_sensor.test": "on"},
            assume_for_seconds=60,
        )
        self.assertEqual(result["summary"]["blocked"], 1)
        self.assertEqual(result["summary"]["matched"], 1)

    def test_simulate_for_rule_non_matching_does_not_block(self):
        """A for-rule stopper whose child condition is false should not block."""
        self._make_rule(
            "For Stopper",
            RuleKind.TRIGGER,
            100,
            stop_processing=True,
            stop_group="g",
            for_seconds=30,
            match="off",
        )
        self._make_rule("Runner", RuleKind.TRIGGER, 1, stop_group="g")

        result = simulate_rules(entity_states={"binary_sensor.test": "on"})
        self.assertEqual(result["summary"]["blocked"], 0)
        self.assertEqual(result["summary"]["matched"], 1)

    def test_simulate_stopper_appears_in_matched_rules(self):
        """The stopper rule itself should appear in matched_rules with its actions."""
        stopper = self._make_rule("Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")

        result = simulate_rules(entity_states={"binary_sensor.test": "on"})
        matched_ids = [r["id"] for r in result["matched_rules"]]
        self.assertIn(stopper.id, matched_ids)
        stopper_entry = next(r for r in result["matched_rules"] if r["id"] == stopper.id)
        self.assertEqual(stopper_entry["actions"], [{"action": "test_action"}])

    def test_simulate_chain_of_stoppers_only_first_fires(self):
        """In simulation, only the highest-priority stopper in a group matches; lower stoppers are blocked."""
        high = self._make_rule("High Stopper", RuleKind.TRIGGER, 100, stop_processing=True, stop_group="g")
        mid = self._make_rule("Mid Stopper", RuleKind.TRIGGER, 50, stop_processing=True, stop_group="g")
        low = self._make_rule("Low Runner", RuleKind.TRIGGER, 1, stop_group="g")

        result = simulate_rules(entity_states={"binary_sensor.test": "on"})
        self.assertEqual(result["summary"]["matched"], 1)
        self.assertEqual(result["summary"]["blocked"], 2)

        blocked_entries = [r for r in result["non_matching_rules"] if r.get("blocked_by_stop_processing")]
        blocked_ids = {e["id"] for e in blocked_entries}
        self.assertEqual(blocked_ids, {mid.id, low.id})
        for entry in blocked_entries:
            self.assertEqual(entry["blocked_by_rule_id"], high.id)
            self.assertEqual(entry["blocked_by_stop_group"], "g")
