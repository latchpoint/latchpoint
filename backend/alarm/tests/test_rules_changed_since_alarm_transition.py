"""ADR-0108: per-condition ``changed_since_alarm_transition`` flag on ``entity_state``.

Evaluator, explain-trace and validation contract. Uses a fake repositories
object so these run as ``SimpleTestCase`` (no DB).
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from alarm.rules.conditions import (
    eval_condition_with_context,
)

DOOR = "binary_sensor.side_fence_door_sensor_door"


def _node(flag: bool | None = True) -> dict:
    """Build an ``entity_state`` node; ``flag=None`` omits the key entirely."""
    node = {"op": "entity_state", "entity_id": DOOR, "equals": "on"}
    if flag is not None:
        node["changed_since_alarm_transition"] = flag
    return node


def _repos(entered_at):
    """Minimal repositories double exposing only what the evaluator reads."""
    return SimpleNamespace(
        get_alarm_state=lambda: "armed_away",
        get_alarm_state_entered_at=lambda: entered_at,
    )


class ChangedSinceAlarmTransitionConditionTests(SimpleTestCase):
    def setUp(self):
        self.entered_at = timezone.now()
        self.stale = self.entered_at - timedelta(minutes=10)
        self.fresh = self.entered_at + timedelta(seconds=1)

    def test_ac_1_stale_entity_is_false_with_flag_and_true_without(self):
        """AC-1: entity already ``on`` before ``entered_at`` → flagged node is false, unflagged is true."""
        state = {DOOR: "on"}
        changed = {DOOR: self.stale}
        self.assertFalse(
            eval_condition_with_context(
                _node(True),
                entity_state=state,
                now=self.entered_at,
                repos=_repos(self.entered_at),
                entity_last_changed=changed,
            )
        )
        self.assertTrue(
            eval_condition_with_context(
                _node(None),
                entity_state=state,
                now=self.entered_at,
                repos=_repos(self.entered_at),
                entity_last_changed=changed,
            )
        )
