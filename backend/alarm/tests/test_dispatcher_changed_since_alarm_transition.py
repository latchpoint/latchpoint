"""ADR-0108: dispatcher path supplies ``last_changed`` to the scoped repositories (AC-8)."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase

from accounts.models import User
from alarm.dispatcher.dispatcher import EntityChangeBatch, RuleDispatcher, invalidate_entity_rule_cache
from alarm.dispatcher.entity_extractor import SYSTEM_ALARM_STATE_ENTITY_ID
from alarm.models import AlarmSettingsProfile, AlarmState, Entity, Rule, RuleEntityRef
from alarm.state_machine.transitions import arm, get_current_snapshot
from alarm.tests.settings_test_utils import set_profile_settings

DOOR = "binary_sensor.side_fence_door_sensor_door"


class ChangedSinceAlarmTransitionDispatcherTests(TestCase):
    def setUp(self):
        invalidate_entity_rule_cache()
        self.user = User.objects.create_user(email="adr0108-dispatch@example.com", password="pass")
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
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        self.entered_at = get_current_snapshot(process_timers=False).entered_at

        self.door = Entity.objects.create(
            entity_id=DOOR,
            domain="binary_sensor",
            name="Side fence door",
            last_state="on",
            last_changed=self.entered_at - timedelta(minutes=10),
            source="home_assistant",
        )
        self.alarm_entity = Entity.objects.create(
            entity_id=SYSTEM_ALARM_STATE_ENTITY_ID, domain="__system", name="Alarm state"
        )
        self.rule = Rule.objects.create(
            name="trigger",
            kind="trigger",
            enabled=True,
            priority=90,
            schema_version=1,
            definition={
                "when": {
                    "op": "all",
                    "children": [
                        {"op": "alarm_state_in", "states": [AlarmState.ARMED_AWAY]},
                        {
                            "op": "entity_state",
                            "entity_id": DOOR,
                            "equals": "on",
                            "source": "home_assistant",
                            "changed_since_alarm_transition": True,
                        },
                    ],
                },
                "then": [],
            },
        )
        RuleEntityRef.objects.create(rule=self.rule, entity=self.door)
        RuleEntityRef.objects.create(rule=self.rule, entity=self.alarm_entity)

    def _dispatch(self, entity_ids: set[str], changed_at):
        dispatcher = RuleDispatcher()
        dispatcher._dispatch_batch(EntityChangeBatch(source="test", entity_ids=entity_ids, changed_at=changed_at))
        return dispatcher._stats

    def test_ac_8_scoped_maps_share_one_query_and_arm_edge_does_not_fire(self):
        """AC-8: ``_get_entity_maps_for_rules`` yields state + last_changed from one Entity query,
        and the incident shape (alarm-state batch, door already open) does not fire."""
        dispatcher = RuleDispatcher()
        with self.assertNumQueries(2):  # RuleEntityRef lookup + one Entity query, same as before ADR-0108
            state_map, last_changed_map = dispatcher._get_entity_maps_for_rules(
                rules=[self.rule], changed_entity_ids={SYSTEM_ALARM_STATE_ENTITY_ID}
            )
        self.assertEqual(state_map[DOOR], "on")
        self.assertEqual(last_changed_map[DOOR], self.door.last_changed)
        self.assertEqual(set(state_map), set(last_changed_map))

        stats = self._dispatch({SYSTEM_ALARM_STATE_ENTITY_ID}, self.entered_at)
        self.assertEqual(stats.rules_fired, 0, "already-open door must not fire on the arm edge")

        fresh = self.entered_at + timedelta(minutes=1)
        Entity.objects.filter(pk=self.door.pk).update(last_state="off", last_changed=fresh - timedelta(seconds=30))
        self._dispatch({DOOR}, fresh - timedelta(seconds=30))
        Entity.objects.filter(pk=self.door.pk).update(last_state="on", last_changed=fresh)
        stats = self._dispatch({DOOR}, fresh)
        self.assertEqual(stats.rules_fired, 1, "door re-opened after arm fires through the dispatcher")
