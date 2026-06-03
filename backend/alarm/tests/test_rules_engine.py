from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm import rules_engine
from alarm.models import AlarmSettingsProfile, AlarmState, Entity, Rule, RuleRuntimeState
from alarm.state_machine.transitions import arm, get_current_snapshot, timer_expired
from alarm.tests.settings_test_utils import set_profile_settings


class RuleEngineForTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rules@example.com", password="pass")
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            profile,
            delay_time=5,
            arming_time=0,
            state_overrides={AlarmState.ARMED_AWAY: {"arming_time": 0}},
            trigger_time=5,
            code_arm_required=False,
        )
        get_current_snapshot(process_timers=False)

    def test_for_rule_schedules_then_fires(self):
        Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front door",
            last_state="on",
        )
        rule = Rule.objects.create(
            name="Trigger after 5s",
            kind="trigger",
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {
                    "op": "for",
                    "seconds": 5,
                    "child": {
                        "op": "entity_state",
                        "entity_id": "binary_sensor.front_door",
                        "equals": "on",
                    },
                },
                # delay_seconds: 0 → trigger immediately; this test asserts the `for:`
                # schedule-then-fire path, not the global entry-delay behavior.
                "then": [{"type": "alarm_trigger", "delay_seconds": 0}],
            },
        )

        arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot = timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)

        now = timezone.now()
        result = rules_engine.run_rules(now=now, actor_user=self.user)
        self.assertEqual(result.scheduled, 1)
        runtime = RuleRuntimeState.objects.get(rule=rule, node_id="when")
        self.assertIsNotNone(runtime.scheduled_for)

        later = now + timedelta(seconds=6)
        result = rules_engine.run_rules(now=later, actor_user=self.user)
        self.assertGreaterEqual(result.fired, 1)
        snapshot = get_current_snapshot(process_timers=False)
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)

        # Condition remains true; do not schedule or fire again until it goes false.
        again = later + timedelta(seconds=1)
        result = rules_engine.run_rules(now=again, actor_user=self.user)
        self.assertEqual(result.scheduled, 0)
        self.assertEqual(result.fired, 0)

    def test_timer_fire_uses_empty_trigger_context_even_with_unrelated_batch(self):
        """ADR-0088 regression: timer fires must not bind ``{{trigger.*}}`` to the
        dispatcher batch in flight, even when that batch happens to include an
        entity referenced by the rule's ``when`` AST. AC-10 only exercises
        ``triggering_entity_ids=None``; this guards the non-empty-but-unrelated
        case.
        """
        Entity.objects.create(
            entity_id="binary_sensor.back_door",
            domain="binary_sensor",
            name="Back Door",
            last_state="on",
        )
        Rule.objects.create(
            name="Timer fire",
            kind="trigger",
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {
                    "op": "for",
                    "seconds": 5,
                    "child": {
                        "op": "entity_state",
                        "entity_id": "binary_sensor.back_door",
                        "equals": "on",
                    },
                },
                "then": [{"type": "alarm_trigger"}],
            },
        )

        captured: dict = {}

        def spy_execute(*, rule, actions, now, actor_user, triggers):
            """Record the TriggerContext so the test can assert on it."""
            captured["triggers"] = triggers
            return {"results": []}

        # T=0: schedule the timer (no batch — first observation).
        now = timezone.now()
        rules_engine.run_rules(now=now, actor_user=self.user, execute_actions_func=spy_execute)

        # T=6: timer is due. The dispatcher batch happens to include back_door —
        # the same entity referenced by the rule's `when` AST. Pre-fix this would
        # have populated trigger=Back Door; post-fix it must remain empty.
        later = now + timedelta(seconds=6)
        rules_engine.run_rules(
            now=later,
            actor_user=self.user,
            triggering_entity_ids=["binary_sensor.back_door"],
            execute_actions_func=spy_execute,
        )

        triggers = captured.get("triggers")
        self.assertIsNotNone(triggers, "spy was not invoked at timer-fire time")
        self.assertIsNone(triggers.trigger)
        self.assertEqual(triggers.triggers, [])
        self.assertEqual(triggers.fire_source, "timer")
