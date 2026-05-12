"""Tests for the PendingAction queue (ADR-0091).

Covers:
- Handler enqueue paths (alarm_trigger + send_notification)
- Scheduler task lifecycle (fire / fail / stale-cancel)
- Cancellation hooks (disarm signal, rule delete, rule disable, WHEN-false,
  manual API)
- API list + cancel endpoints
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from alarm.models import (
    AlarmSettingsProfile,
    AlarmState,
    AlarmStateSnapshot,
    Entity,
    PendingAction,
    PendingActionCancelReason,
    PendingActionStatus,
    Rule,
)
from alarm.rules.action_handlers import ActionContext
from alarm.rules.action_handlers.alarm_trigger import execute as alarm_trigger_execute
from alarm.rules.action_handlers.send_notification import execute as send_notification_execute
from alarm.rules.template_render import TriggerContext
from alarm.state_machine.timing import base_timing
from alarm.state_machine.transitions import disarm
from alarm.tasks import fire_due_pending_actions
from alarm.tests.settings_test_utils import set_profile_settings

# ── helpers ──────────────────────────────────────────────────────────────────


class _FakeAlarmServices:
    """Stub matching the AlarmServices protocol; lets us control reported state."""

    def __init__(self, *, current_state: str = AlarmState.ARMED_AWAY):
        self.current_state = current_state
        self.calls: list[tuple] = []

    def get_current_snapshot(self, *, process_timers: bool):
        snap = MagicMock()
        snap.current_state = self.current_state
        return snap

    def disarm(self, *, user=None, code=None, reason: str = ""):
        self.calls.append(("disarm", user, reason))

    def arm(self, *, target_state: str, user=None, code=None, reason: str = ""):
        self.calls.append(("arm", target_state, user, reason))

    def trigger(self, *, user=None, reason: str = ""):
        self.calls.append(("trigger", user, reason))


def _make_ctx(rule: Rule, *, action_index: int = 0, current_state: str = AlarmState.ARMED_AWAY) -> ActionContext:
    fake_alarm = _FakeAlarmServices(current_state=current_state)
    return ActionContext(
        rule=rule,
        actor_user=None,
        alarm_services=fake_alarm,
        ha=MagicMock(),
        zwavejs=MagicMock(),
        zigbee2mqtt=MagicMock(),
        triggers=TriggerContext.empty(),
        action_index=action_index,
    )


def _make_rule(*, name: str = "Test rule", definition: dict | None = None) -> Rule:
    return Rule.objects.create(
        name=name,
        kind="trigger",
        enabled=True,
        priority=1,
        schema_version=1,
        definition=definition or {"when": {}, "then": []},
    )


def _seed_profile(*, delay_time: int = 5) -> AlarmSettingsProfile:
    profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
    set_profile_settings(
        profile,
        delay_time=delay_time,
        arming_time=0,
        trigger_time=5,
        code_arm_required=False,
        disarm_after_trigger=False,
    )
    return profile


# ── handler enqueue paths ────────────────────────────────────────────────────


class AlarmTriggerEnqueueTests(TestCase):
    def setUp(self):
        _seed_profile()
        self.rule = _make_rule(name="alarm trigger rule")

    def test_no_delay_executes_immediately(self):
        ctx = _make_ctx(self.rule)
        result, error = alarm_trigger_execute({"type": "alarm_trigger"}, ctx)
        self.assertTrue(result["ok"])
        self.assertNotIn("deferred", result)
        self.assertIsNone(error)
        self.assertEqual([c[0] for c in ctx.alarm_services.calls], ["trigger"])
        self.assertEqual(PendingAction.objects.count(), 0)

    def test_positive_delay_enqueues(self):
        ctx = _make_ctx(self.rule)
        result, error = alarm_trigger_execute({"type": "alarm_trigger", "delay_seconds": 15}, ctx)
        self.assertTrue(result["ok"])
        self.assertTrue(result["deferred"])
        self.assertEqual(result["delay_seconds"], 15)
        self.assertIsNone(error)
        # Did NOT invoke trigger() immediately:
        self.assertEqual(ctx.alarm_services.calls, [])
        # And created a PendingAction:
        pa = PendingAction.objects.get(id=result["pending_action_id"])
        self.assertEqual(pa.status, PendingActionStatus.SCHEDULED)
        self.assertEqual(pa.rule_id, self.rule.id)
        self.assertEqual(pa.delay_seconds, 15)
        self.assertEqual(pa.armed_state_at_schedule, AlarmState.ARMED_AWAY)

    def test_negative_delay_treated_as_zero(self):
        ctx = _make_ctx(self.rule)
        result, _ = alarm_trigger_execute({"type": "alarm_trigger", "delay_seconds": -5}, ctx)
        self.assertTrue(result["ok"])
        self.assertNotIn("deferred", result)
        self.assertEqual(PendingAction.objects.count(), 0)

    def test_bool_delay_treated_as_zero(self):
        # bool subclasses int in Python; handler must reject it.
        ctx = _make_ctx(self.rule)
        result, _ = alarm_trigger_execute({"type": "alarm_trigger", "delay_seconds": True}, ctx)
        self.assertTrue(result["ok"])
        self.assertNotIn("deferred", result)
        self.assertEqual(PendingAction.objects.count(), 0)


class SendNotificationEnqueueTests(TestCase):
    def setUp(self):
        _seed_profile()
        self.rule = _make_rule(name="notify rule")
        self.provider_id = str(uuid4())

    def test_positive_delay_enqueues(self):
        ctx = _make_ctx(self.rule)
        action = {
            "type": "send_notification",
            "provider_id": self.provider_id,
            "message": "Heads-up",
            "delay_seconds": 30,
        }
        result, error = send_notification_execute(action, ctx)
        self.assertTrue(result["ok"])
        self.assertTrue(result["deferred"])
        self.assertEqual(result["delay_seconds"], 30)
        self.assertIsNone(error)
        pa = PendingAction.objects.get(id=result["pending_action_id"])
        self.assertEqual(pa.action_payload["delay_seconds"], 30)
        self.assertEqual(pa.action_payload["provider_id"], self.provider_id)

    def test_no_delay_falls_through_to_normal_dispatch(self):
        # Without a delay, the existing notification dispatcher path runs. We
        # patch it so the test stays a pure unit test (no provider config needed).
        ctx = _make_ctx(self.rule)
        with patch("alarm.rules.action_handlers.send_notification.get_notification_dispatcher") as dispatcher:
            dispatcher.return_value.enqueue.return_value = (
                None,
                MagicMock(message="no provider", error_code="missing"),
            )
            result, _ = send_notification_execute(
                {
                    "type": "send_notification",
                    "provider_id": self.provider_id,
                    "message": "hi",
                },
                ctx,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(PendingAction.objects.count(), 0)


# ── fire-due scheduler task ──────────────────────────────────────────────────


class FireDuePendingActionsTests(TestCase):
    def setUp(self):
        self.profile = _seed_profile()
        # Snapshot so trigger() can run when fire-task dispatches alarm_trigger.
        AlarmStateSnapshot.objects.create(
            current_state=AlarmState.ARMED_AWAY,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            last_transition_reason="setup",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )
        self.rule = _make_rule()

    def _enqueue(self, *, fire_at, status=PendingActionStatus.SCHEDULED, payload=None) -> PendingAction:
        return PendingAction.objects.create(
            rule=self.rule,
            action_index=0,
            action_payload=payload or {"type": "alarm_trigger", "delay_seconds": 5},
            delay_seconds=5,
            fire_at=fire_at,
            status=status,
            armed_state_at_schedule=AlarmState.ARMED_AWAY,
        )

    def test_fires_due_row_and_marks_fired(self):
        pa = self._enqueue(fire_at=timezone.now() - timedelta(seconds=1))
        result = fire_due_pending_actions()
        self.assertEqual(result["fired"], 1)
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.FIRED)
        self.assertIsNotNone(pa.fired_at)
        # delay_seconds must have been stripped before dispatch — otherwise the
        # handler would re-enqueue. Confirm by checking the alarm transitioned.
        snap = AlarmStateSnapshot.objects.first()
        self.assertEqual(snap.current_state, AlarmState.TRIGGERED)

    def test_skips_rows_in_terminal_state(self):
        pa = self._enqueue(
            fire_at=timezone.now() - timedelta(seconds=1),
            status=PendingActionStatus.CANCELLED,
        )
        result = fire_due_pending_actions()
        self.assertEqual(result["fired"], 0)
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.CANCELLED)

    def test_skips_rows_with_future_fire_at(self):
        pa = self._enqueue(fire_at=timezone.now() + timedelta(seconds=30))
        result = fire_due_pending_actions()
        self.assertEqual(result["fired"], 0)
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.SCHEDULED)

    def test_stale_rows_are_auto_cancelled(self):
        pa = self._enqueue(fire_at=timezone.now() - timedelta(minutes=10))
        result = fire_due_pending_actions()
        self.assertGreaterEqual(result["stale_cancelled"], 1)
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.CANCELLED)
        self.assertEqual(pa.cancel_reason, PendingActionCancelReason.STALE_AFTER_RESTART)

    def test_unsupported_action_type_marked_failed(self):
        pa = self._enqueue(
            fire_at=timezone.now() - timedelta(seconds=1),
            payload={"type": "not_a_real_action"},
        )
        result = fire_due_pending_actions()
        self.assertEqual(result["failed"], 1)
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.FAILED)


# ── cancellation paths ───────────────────────────────────────────────────────


class CancellationTests(TestCase):
    def setUp(self):
        self.profile = _seed_profile()
        AlarmStateSnapshot.objects.create(
            current_state=AlarmState.ARMED_AWAY,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            last_transition_reason="setup",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )
        self.rule = _make_rule()
        self.user = User.objects.create_user(email="cancel@example.com", password="pass")

    def _enqueue(self, *, armed_state: str = AlarmState.ARMED_AWAY) -> PendingAction:
        return PendingAction.objects.create(
            rule=self.rule,
            action_index=0,
            action_payload={"type": "alarm_trigger", "delay_seconds": 15},
            delay_seconds=15,
            fire_at=timezone.now() + timedelta(seconds=15),
            status=PendingActionStatus.SCHEDULED,
            armed_state_at_schedule=armed_state,
        )

    def test_disarm_cancels_armed_scheduled_actions(self):
        pa = self._enqueue(armed_state=AlarmState.ARMED_AWAY)
        with self.captureOnCommitCallbacks(execute=True):
            disarm(user=self.user, reason="cancel test")
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.CANCELLED)
        self.assertEqual(pa.cancel_reason, PendingActionCancelReason.DISARM)

    def test_disarm_leaves_disarmed_scheduled_actions_alone(self):
        # Rare but legal: a rule that fires while disarmed and queues an action.
        # The setUp snapshot is ARMED_AWAY, so disarm() does flip state and fire
        # the alarm_state_change_committed signal — the receiver IS invoked here.
        # What we're verifying is that `cancel_for_disarm` filters by
        # `armed_state_at_schedule__in=ARMED_STATES`, which excludes this row.
        pa = self._enqueue(armed_state=AlarmState.DISARMED)
        with self.captureOnCommitCallbacks(execute=True):
            disarm(user=self.user, reason="cancel test")
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.SCHEDULED)

    def test_rule_deletion_cancels_its_scheduled_actions(self):
        pa = self._enqueue()
        self.rule.delete()
        # CASCADE deletes the PendingAction row entirely.
        self.assertFalse(PendingAction.objects.filter(id=pa.id).exists())

    def test_rule_disable_cancels_its_scheduled_actions(self):
        pa = self._enqueue()
        self.rule.enabled = False
        self.rule.save()
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.CANCELLED)
        self.assertEqual(pa.cancel_reason, PendingActionCancelReason.RULE_DELETED)

    def test_rule_enable_does_not_cancel(self):
        pa = self._enqueue()
        # Toggle (no real change in enabled=True).
        self.rule.priority = 99
        self.rule.save()
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.SCHEDULED)


class WhenFalseCancellationTests(TestCase):
    """The rules engine cancels queued actions when WHEN flips to not-matched."""

    def setUp(self):
        self.profile = _seed_profile()
        # Snapshot says DISARMED — so the rule's `armed_away` WHEN won't match.
        AlarmStateSnapshot.objects.create(
            current_state=AlarmState.DISARMED,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            last_transition_reason="setup",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )

    def test_when_flipping_to_false_cancels_existing_pending_action(self):
        """A rule that no longer matches WHEN cancels its scheduled actions.

        We seed the row directly to keep this test focused on the cancellation
        hook (the rule engine's enqueue side is exercised by the handler tests).
        The rule's WHEN says `alarm_state_in=[armed_away]`; the current alarm
        state in setUp is DISARMED, so on first evaluation the engine should
        observe ``last_when_matched`` flipping from None → False and cancel.
        """
        from alarm import rules_engine
        from alarm.models import RuleRuntimeState
        from alarm.rules.repositories import default_rule_engine_repositories

        Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front door",
            last_state="on",
        )
        rule = Rule.objects.create(
            name="Door open and armed",
            kind="trigger",
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {"op": "alarm_state_in", "states": [AlarmState.ARMED_AWAY]},
                "then": [{"type": "alarm_trigger", "delay_seconds": 30}],
            },
        )
        # Pretend the engine previously matched this rule and queued an action.
        RuleRuntimeState.objects.create(rule=rule, last_when_matched=True)
        pa = PendingAction.objects.create(
            rule=rule,
            action_index=0,
            action_payload={"type": "alarm_trigger", "delay_seconds": 30},
            delay_seconds=30,
            fire_at=timezone.now() + timedelta(seconds=30),
            status=PendingActionStatus.SCHEDULED,
            armed_state_at_schedule=AlarmState.ARMED_AWAY,
        )

        # Now the alarm is DISARMED so the rule's WHEN flips to False.
        repos = default_rule_engine_repositories()
        with self.captureOnCommitCallbacks(execute=True):
            rules_engine.run_rules(now=timezone.now(), repos=repos)

        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.CANCELLED)
        self.assertEqual(pa.cancel_reason, PendingActionCancelReason.WHEN_FALSE)


# ── API endpoints ────────────────────────────────────────────────────────────


class PendingActionsApiTests(TestCase):
    def setUp(self):
        _seed_profile()
        self.user = User.objects.create_user(email="api@example.com", password="pass")
        self.rule = _make_rule()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _enqueue(self, *, status=PendingActionStatus.SCHEDULED) -> PendingAction:
        return PendingAction.objects.create(
            rule=self.rule,
            action_index=0,
            action_payload={"type": "alarm_trigger", "delay_seconds": 15},
            delay_seconds=15,
            fire_at=timezone.now() + timedelta(seconds=15),
            status=status,
            armed_state_at_schedule=AlarmState.ARMED_AWAY,
        )

    def test_list_default_returns_only_scheduled(self):
        scheduled = self._enqueue()
        self._enqueue(status=PendingActionStatus.FIRED)
        response = self.client.get(reverse("alarm-pending-actions"))
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        ids = [row["id"] for row in rows]
        self.assertEqual(ids, [scheduled.id])

    def test_list_status_all_returns_every_row(self):
        self._enqueue()
        self._enqueue(status=PendingActionStatus.FIRED)
        response = self.client.get(reverse("alarm-pending-actions"), {"status": "all"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 2)

    def test_cancel_endpoint_transitions_to_cancelled(self):
        pa = self._enqueue()
        response = self.client.post(reverse("alarm-pending-action-cancel", args=[pa.id]))
        self.assertEqual(response.status_code, 200)
        body = response.json()["data"]
        self.assertEqual(body["status"], PendingActionStatus.CANCELLED)
        self.assertEqual(body["cancel_reason"], PendingActionCancelReason.MANUAL)
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.CANCELLED)

    def test_cancel_endpoint_returns_404_if_already_terminal(self):
        pa = self._enqueue(status=PendingActionStatus.FIRED)
        response = self.client.post(reverse("alarm-pending-action-cancel", args=[pa.id]))
        self.assertEqual(response.status_code, 404)
