"""ADR-0108: ``changed_since_alarm_transition`` through ``run_rules`` / ``simulate_rules`` (DB-backed)."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase

from accounts.models import User
from alarm import rules_engine
from alarm.models import AlarmSettingsProfile, AlarmState, Entity, Rule
from alarm.state_machine.transitions import arm, get_current_snapshot
from alarm.tests.settings_test_utils import set_profile_settings

DOOR_A = "binary_sensor.side_fence_door_sensor_door"
DOOR_B = "binary_sensor.front_door_window_door_is_open"
GUEST = "input_boolean.guest_mode"


def _door(entity_id: str, flag: bool = True) -> dict:
    node = {"op": "entity_state", "entity_id": entity_id, "equals": "on", "source": "home_assistant"}
    if flag:
        node["changed_since_alarm_transition"] = True
    return node


def _armed_away() -> dict:
    return {"op": "alarm_state_in", "states": [AlarmState.ARMED_AWAY]}


class ChangedSinceAlarmTransitionRunRulesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="adr0108@example.com", password="pass")
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
        # Arm with zero exit delay → snapshot.entered_at is the armed_away transition instant.
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        self.entered_at = get_current_snapshot(process_timers=False).entered_at
        self.stale = self.entered_at - timedelta(minutes=10)
        self.executed: list[int] = []

    def _entity(self, entity_id: str, state: str, last_changed) -> Entity:
        return Entity.objects.create(
            entity_id=entity_id,
            domain=entity_id.split(".", 1)[0],
            name=entity_id,
            last_state=state,
            last_changed=last_changed,
            source="home_assistant",
        )

    def _set(self, entity: Entity, state: str, last_changed) -> None:
        Entity.objects.filter(pk=entity.pk).update(last_state=state, last_changed=last_changed)

    def _rule(self, when: dict, name: str = "trigger") -> Rule:
        return Rule.objects.create(
            name=name,
            kind="trigger",
            enabled=True,
            priority=90,
            schema_version=1,
            definition={"when": when, "then": [{"type": "alarm_trigger"}]},
        )

    def _fake_execute(self, *, rule, actions, now, actor_user, triggers):
        self.executed.append(rule.id)
        return {"ok": True, "actions": []}

    @staticmethod
    def _fake_log(**kwargs):
        return None

    def _run(self, at):
        return rules_engine.run_rules(
            now=at,
            actor_user=self.user,
            execute_actions_func=self._fake_execute,
            log_action_func=self._fake_log,
        )

    def test_ac_4_pre_existing_open_door_does_not_fire_but_fresh_changes_do(self):
        """AC-4: A open before arm → no fire; B opens after → fires once; A cycles after → fires again."""
        door_a = self._entity(DOOR_A, "on", self.stale)
        door_b = self._entity(DOOR_B, "off", self.stale)
        self._rule(
            {"op": "all", "children": [_armed_away(), {"op": "any", "children": [_door(DOOR_A), _door(DOOR_B)]}]}
        )

        t = self.entered_at + timedelta(seconds=1)
        self.assertEqual(self._run(t).fired, 0, "already-open door must not fire on the arm edge")

        self._set(door_b, "on", self.entered_at + timedelta(minutes=1))
        self.assertEqual(self._run(t + timedelta(minutes=1)).fired, 1, "second door opening after arm fires")
        self.assertEqual(self._run(t + timedelta(minutes=1, seconds=1)).fired, 0, "no re-fire without a new edge")

        self._set(door_b, "off", self.entered_at + timedelta(minutes=2))
        self.assertEqual(self._run(t + timedelta(minutes=2)).fired, 0)

        self._set(door_a, "off", self.entered_at + timedelta(minutes=3))
        self.assertEqual(self._run(t + timedelta(minutes=3)).fired, 0)
        self._set(door_a, "on", self.entered_at + timedelta(minutes=4))
        self.assertEqual(self._run(t + timedelta(minutes=4)).fired, 1, "door A re-opened after arm fires")
        self.assertEqual(len(self.executed), 2)

    def test_ac_5_unflagged_level_condition_in_same_rule_is_unaffected(self):
        """AC-5: a stale, unflagged ``input_boolean`` stays level; only the flagged door is edge-gated."""
        guest = self._entity(GUEST, "on", self.stale)
        door_a = self._entity(DOOR_A, "on", self.stale)
        self._rule(
            {
                "op": "all",
                "children": [
                    _armed_away(),
                    {"op": "entity_state", "entity_id": GUEST, "equals": "on", "source": "home_assistant"},
                    _door(DOOR_A),
                ],
            }
        )
        t = self.entered_at + timedelta(seconds=1)
        self.assertEqual(self._run(t).fired, 0, "stale flagged door blocks the rule")

        self._set(door_a, "off", self.entered_at + timedelta(minutes=1))
        self._run(t + timedelta(minutes=1))
        self._set(door_a, "on", self.entered_at + timedelta(minutes=2))
        self.assertEqual(self._run(t + timedelta(minutes=2)).fired, 1, "stale unflagged guest_mode still counts")
        self.assertEqual(Entity.objects.get(pk=guest.pk).last_changed, self.stale)
