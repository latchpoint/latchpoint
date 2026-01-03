from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from alarm.rules.conditions import eval_condition_explain_with_context, eval_condition_with_context
from alarm.rules.repositories import default_rule_engine_repositories
from integrations_frigate.models import FrigateDetection


class RulesFrigatePersonDetectedConditionTests(TestCase):
    def test_matches_when_recent_person_detection_meets_threshold(self):
        now = timezone.now()
        FrigateDetection.objects.create(
            provider="frigate",
            event_id="evt1",
            label="person",
            camera="backyard",
            zones=["yard"],
            confidence_pct=92.0,
            observed_at=now,
            source_topic="frigate/events",
            raw={},
        )

        node = {
            "op": "frigate_person_detected",
            "cameras": ["backyard"],
            "zones": ["yard"],
            "within_seconds": 30,
            "min_confidence_pct": 90,
            "aggregation": "max",
            "on_unavailable": "treat_as_no_match",
        }

        repos = default_rule_engine_repositories()
        self.assertTrue(eval_condition_with_context(node, entity_state={}, now=now, repos=repos))

        ok, trace = eval_condition_explain_with_context(node, entity_state={}, now=now, repos=repos)
        self.assertTrue(ok)
        self.assertEqual(trace["op"], "frigate_person_detected")
        self.assertEqual(trace["candidates_count"], 1)

    def test_zone_filter_requires_overlap(self):
        now = timezone.now()
        FrigateDetection.objects.create(
            provider="frigate",
            event_id="evt1",
            label="person",
            camera="backyard",
            zones=["yard"],
            confidence_pct=99.0,
            observed_at=now,
            source_topic="frigate/events",
            raw={},
        )

        node = {
            "op": "frigate_person_detected",
            "cameras": ["backyard"],
            "zones": ["driveway"],
            "within_seconds": 30,
            "min_confidence_pct": 90,
            "aggregation": "max",
        }

        repos = default_rule_engine_repositories()
        self.assertFalse(eval_condition_with_context(node, entity_state={}, now=now, repos=repos))


class RulesAlarmStateInConditionTests(TestCase):
    def test_matches_when_current_alarm_state_in_list(self):
        from alarm.models import AlarmSettingsProfile, AlarmStateSnapshot

        profile = AlarmSettingsProfile.objects.create(name="P1", is_active=True)
        AlarmStateSnapshot.objects.create(
            current_state="armed_away",
            previous_state="disarmed",
            target_armed_state="armed_away",
            entered_at=timezone.now(),
            settings_profile=profile,
        )

        node = {"op": "alarm_state_in", "states": ["armed_away", "armed_home"]}
        repos = default_rule_engine_repositories()
        self.assertTrue(eval_condition_with_context(node, entity_state={}, now=timezone.now(), repos=repos))
