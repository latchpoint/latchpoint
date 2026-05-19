"""Tests for the PendingAction queue (ADR-0091, superseded by ADR-0094).

Under ADR-0094 the queue is generic: every rule action with
``delay_seconds > 0`` is enqueued by the executor. The handlers do not
manage their own delay branches anymore.

This module covers:
- ``send_notification`` enqueue path (via the executor's generic delay handling)
- Scheduler ``fire_due_pending_actions`` task lifecycle (fire / fail / stale-cancel)
- Cancellation hooks (disarm signal, rule delete, rule disable, manual API)
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
    PendingAction,
    PendingActionCancelReason,
    PendingActionStatus,
    Rule,
)
from alarm.rules.action_executor import execute_actions
from alarm.rules.action_handlers import ActionContext
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

    def set_state(self, *, new_state, user=None, reason: str = "", exit_at=None, metadata=None):
        self.calls.append(("set_state", new_state, user, reason))
        snap = MagicMock()
        snap.current_state = new_state
        return snap


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


# ── executor-level enqueue (ADR-0094 §3.3) ───────────────────────────────────


class GenericDelayEnqueueTests(TestCase):
    """The executor enqueues any action with ``delay_seconds > 0`` through PendingAction."""

    def setUp(self):
        self.profile = _seed_profile()
        AlarmStateSnapshot.objects.create(
            current_state=AlarmState.ARMED_AWAY,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            last_transition_reason="setup",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )
        self.rule = _make_rule(name="notify rule")
        self.provider_id = str(uuid4())

    def test_send_notification_with_delay_enqueues(self):
        actions = [
            {
                "type": "send_notification",
                "provider_id": self.provider_id,
                "message": "Heads-up",
                "delay_seconds": 30,
            }
        ]
        result = execute_actions(rule=self.rule, actions=actions, now=timezone.now())
        action_result = result["actions"][0]
        self.assertTrue(action_result["ok"])
        self.assertTrue(action_result["deferred"])
        self.assertEqual(action_result["delay_seconds"], 30)
        pa = PendingAction.objects.get(id=action_result["pending_action_id"])
        self.assertEqual(pa.action_payload["type"], "send_notification")

    def test_alarm_trigger_with_delay_enqueues(self):
        actions = [{"type": "alarm_trigger", "delay_seconds": 15}]
        result = execute_actions(rule=self.rule, actions=actions, now=timezone.now())
        action_result = result["actions"][0]
        self.assertTrue(action_result["ok"])
        self.assertTrue(action_result["deferred"])
        pa = PendingAction.objects.get(id=action_result["pending_action_id"])
        self.assertEqual(pa.action_payload["type"], "alarm_trigger")
        self.assertEqual(pa.delay_seconds, 15)

    def test_negative_delay_runs_immediately(self):
        actions = [
            {
                "type": "send_notification",
                "provider_id": self.provider_id,
                "message": "Heads-up",
                "delay_seconds": -1,
            }
        ]
        with patch("alarm.rules.action_handlers.send_notification.get_notification_dispatcher") as dispatcher:
            dispatcher.return_value.enqueue.return_value = (
                None,
                MagicMock(message="no provider", error_code="missing"),
            )
            result = execute_actions(rule=self.rule, actions=actions, now=timezone.now())
        action_result = result["actions"][0]
        self.assertNotIn("deferred", action_result)
        self.assertEqual(PendingAction.objects.count(), 0)

    def test_bool_delay_runs_immediately(self):
        # bool is an int subclass in Python; the validator must reject it.
        actions = [{"type": "alarm_trigger", "delay_seconds": True}]
        with patch("alarm.state_machine.transitions.trigger") as trigger:
            execute_actions(rule=self.rule, actions=actions, now=timezone.now())
        self.assertEqual(PendingAction.objects.count(), 0)
        trigger.assert_called_once()


# ── fire-due scheduler task ──────────────────────────────────────────────────


class FireDuePendingActionsTests(TestCase):
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
        self.provider_id = str(uuid4())

    def _enqueue(self, *, fire_at, status=PendingActionStatus.SCHEDULED, payload=None) -> PendingAction:
        return PendingAction.objects.create(
            rule=self.rule,
            action_index=0,
            action_payload=payload
            or {
                "type": "send_notification",
                "provider_id": self.provider_id,
                "message": "Heads-up",
                "delay_seconds": 5,
            },
            delay_seconds=5,
            fire_at=fire_at,
            status=status,
            armed_state_at_schedule=AlarmState.ARMED_AWAY,
        )

    def test_fires_due_row_and_marks_fired(self):
        pa = self._enqueue(fire_at=timezone.now() - timedelta(seconds=1))
        with patch("alarm.rules.action_handlers.send_notification.get_notification_dispatcher") as dispatcher:
            dispatcher.return_value.enqueue.return_value = (
                MagicMock(id=42, status="queued"),
                None,
            )
            result = fire_due_pending_actions()
        self.assertEqual(result["fired"], 1)
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.FIRED)
        self.assertIsNotNone(pa.fired_at)

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
        self.provider_id = str(uuid4())

    def _enqueue(self, *, armed_state: str = AlarmState.ARMED_AWAY) -> PendingAction:
        return PendingAction.objects.create(
            rule=self.rule,
            action_index=0,
            action_payload={
                "type": "send_notification",
                "provider_id": self.provider_id,
                "message": "Heads-up",
                "delay_seconds": 15,
            },
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
        # `cancel_for_disarm` filters by `armed_state_at_schedule__in=ARMED_STATES`,
        # which excludes this row.
        pa = self._enqueue(armed_state=AlarmState.DISARMED)
        with self.captureOnCommitCallbacks(execute=True):
            disarm(user=self.user, reason="cancel test")
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.SCHEDULED)

    def test_rule_deletion_cancels_its_scheduled_actions(self):
        pa = self._enqueue()
        self.rule.delete()
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

    def test_when_flipping_to_false_does_not_cancel(self):
        """Ring-panel semantic: WHEN-false must NOT cancel queued send_notification.

        Under the revised ADR-0091, only disarm, rule delete/disable, or explicit
        operator cancel stop a queued action. This guards against accidentally
        re-introducing the WHEN-false hook.
        """
        from alarm import rules_engine
        from alarm.models import Entity, RuleRuntimeState
        from alarm.rules.repositories import default_rule_engine_repositories

        Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front door",
            last_state="on",
        )
        # Switch the snapshot to DISARMED so the rule's WHEN flips false.
        AlarmStateSnapshot.objects.update(current_state=AlarmState.DISARMED)
        rule = Rule.objects.create(
            name="Door open and armed",
            kind="trigger",
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {"op": "alarm_state_in", "states": [AlarmState.ARMED_AWAY]},
                "then": [
                    {
                        "type": "send_notification",
                        "provider_id": self.provider_id,
                        "message": "hi",
                        "delay_seconds": 30,
                    }
                ],
            },
        )
        RuleRuntimeState.objects.create(rule=rule, last_when_matched=True)
        pa = PendingAction.objects.create(
            rule=rule,
            action_index=0,
            action_payload={
                "type": "send_notification",
                "provider_id": self.provider_id,
                "message": "hi",
                "delay_seconds": 30,
            },
            delay_seconds=30,
            fire_at=timezone.now() + timedelta(seconds=30),
            status=PendingActionStatus.SCHEDULED,
            armed_state_at_schedule=AlarmState.ARMED_AWAY,
        )

        repos = default_rule_engine_repositories()
        with self.captureOnCommitCallbacks(execute=True):
            rules_engine.run_rules(now=timezone.now(), repos=repos)

        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.SCHEDULED)


# ── API endpoints ────────────────────────────────────────────────────────────


class PendingActionsApiTests(TestCase):
    def setUp(self):
        _seed_profile()
        self.user = User.objects.create_user(email="api@example.com", password="pass")
        self.rule = _make_rule()
        self.provider_id = str(uuid4())
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _enqueue(
        self,
        *,
        status=PendingActionStatus.SCHEDULED,
        payload=None,
    ) -> PendingAction:
        return PendingAction.objects.create(
            rule=self.rule,
            action_index=0,
            action_payload=payload
            or {
                "type": "send_notification",
                "provider_id": self.provider_id,
                "message": "Heads-up",
                "delay_seconds": 15,
            },
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

    def test_list_rejects_unknown_status_filter(self):
        response = self.client.get(reverse("alarm-pending-actions"), {"status": "bogus"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_list_clamps_negative_limit(self):
        # Pre-fix: negative limit hit Django's slice and 500'd. Post-fix: clamped to 1.
        self._enqueue()
        self._enqueue()
        response = self.client.get(reverse("alarm-pending-actions"), {"limit": "-5"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)

    def test_cancel_send_notification_transitions_to_cancelled(self):
        pa = self._enqueue()
        response = self.client.post(reverse("alarm-pending-action-cancel", args=[pa.id]))
        self.assertEqual(response.status_code, 200)
        body = response.json()["data"]
        self.assertEqual(body["status"], PendingActionStatus.CANCELLED)
        self.assertEqual(body["cancel_reason"], PendingActionCancelReason.MANUAL)
        pa.refresh_from_db()
        self.assertEqual(pa.status, PendingActionStatus.CANCELLED)

    def test_cancel_endpoint_returns_envelope_404_if_already_terminal(self):
        pa = self._enqueue(status=PendingActionStatus.FIRED)
        response = self.client.post(reverse("alarm-pending-action-cancel", args=[pa.id]))
        self.assertEqual(response.status_code, 404)
        # ADR-0025: error payload must use the {"error": {...}} envelope.
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["status"], "not_found")
