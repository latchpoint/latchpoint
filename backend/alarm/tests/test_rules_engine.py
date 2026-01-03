from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm import rules_engine, services
from alarm.models import AlarmSettingsProfile, AlarmState, Entity, Rule, RuleRuntimeState
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
        services.get_current_snapshot(process_timers=False)

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
                "then": [{"type": "alarm_trigger"}],
            },
        )

        services.arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot = services.timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)

        now = timezone.now()
        result = rules_engine.run_rules(now=now, actor_user=self.user)
        self.assertEqual(result.scheduled, 1)
        runtime = RuleRuntimeState.objects.get(rule=rule, node_id="when")
        self.assertIsNotNone(runtime.scheduled_for)

        later = now + timedelta(seconds=6)
        result = rules_engine.run_rules(now=later, actor_user=self.user)
        self.assertGreaterEqual(result.fired, 1)
        snapshot = services.get_current_snapshot(process_timers=False)
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)
