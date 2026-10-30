"""Issues #126 and #123: the scheduler, Retry, the validity task and the rollup read the per-lock push state.

The new use cases are reached through ``lock_push_uc`` so this module still
imports where they don't exist, and the tests for the behaviour can be run
against the code from before them.
"""

from __future__ import annotations

import importlib
import json
from datetime import time, timedelta
from unittest.mock import patch

from django.apps import apps as django_apps
from django.db import connection
from django.db.models.query import QuerySet
from django.utils import timezone
from integrations_zwavejs.manager import ZwavejsCommandError, ZwavejsCommandValidationError
from rest_framework.test import APITestCase

from alarm.crypto import SettingsEncryption
from alarm.tests.settings_test_utils import EncryptionTestMixin
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.serializers import DoorCodePushSerializer, DoorCodeSerializer
from locks.tests import test_lock_config_sync_api as sync_tests
from locks.tests.test_lock_push import ClearFailingGateway, FakeGateway, _TwoLockUpdateTestBase
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.lock_push import ClearFailure, LockPushFailed, LockUnreachable, push_door_code_to_lock

PENDING = DoorCode.PushState.PENDING
PUSHED = DoorCode.PushState.PUSHED
FAILED = DoorCode.PushState.FAILED
TIMEOUT = "driver TimeoutError after 5.0s"


def _lock_state(assignment: DoorCodeLockAssignment) -> tuple:
    assignment.refresh_from_db()
    return (
        assignment.slot_index,
        assignment.push_state,
        assignment.push_attempt_count,
        assignment.last_push_error,
        assignment.schedule_pending,
    )


class PerNodeGateway(ClearFailingGateway):
    """A FakeGateway whose CC 99 ``set`` or CC 78 schedule fails on chosen nodes.

    ``set_times_out_on``: the ``set`` times out before the lock stores anything.
    ``schedule_fails_on``: maps a node to the exception every CC 78 call raises.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_times_out_on: set[int] = set()
        self.schedule_fails_on: dict[int, Exception] = {}

    def invoke_cc_api(self, *, node_id: int, command_class: int, method_name: str, args=None, timeout_seconds=10.0):
        failure = None
        if command_class == 99 and method_name == "set" and node_id in self.set_times_out_on:
            failure = ZwavejsCommandError(TIMEOUT)
        elif command_class == 78 and node_id in self.schedule_fails_on:
            failure = self.schedule_fails_on[node_id]
        if failure is not None:
            self.invoke_calls.append(
                {"node_id": node_id, "command_class": command_class, "method_name": method_name, "args": args}
            )
            raise failure
        return super().invoke_cc_api(
            node_id=node_id,
            command_class=command_class,
            method_name=method_name,
            args=args,
            timeout_seconds=timeout_seconds,
        )


class _PerLockTestBase(_TwoLockUpdateTestBase):
    def _tick(self, gateway) -> int:
        from locks.tasks import push_pending_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            return push_pending_door_codes()

    def _enforce(self, gateway) -> int:
        from locks.tasks import enforce_door_code_validity

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            return enforce_door_code_validity()

    def _code(self, **fields) -> DoorCode:
        return DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=fields.pop("code_type", DoorCode.CodeType.PERMANENT),
            is_active=fields.pop("is_active", True),
            **fields,
        )

    def _lock(self, code: DoorCode, lock_entity_id: str, **fields) -> DoorCodeLockAssignment:
        return DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=lock_entity_id, **fields)

    def _assignment(self, code: DoorCode, lock_entity_id: str) -> DoorCodeLockAssignment:
        return DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=lock_entity_id)

    @staticmethod
    def _nodes_sent(gateway, command_class: int = 99, method_name: str = "set") -> list[int]:
        return [
            c["node_id"]
            for c in gateway.invoke_calls
            if c["command_class"] == command_class and c["method_name"] == method_name
        ]

    @staticmethod
    def _cap_events(code: DoorCode) -> list[tuple[str, int]]:
        return list(
            DoorCodeEvent.objects.filter(
                door_code=code, event_type=DoorCodeEvent.EventType.CODE_FAILED, metadata__reason="max_attempts_exceeded"
            )
            .order_by("id")
            .values_list("lock_entity_id", "metadata__attempts")
        )


class TerminalFailureOnOneLockTests(_PerLockTestBase):
    """Issue #126: one lock needing a human doesn't stop the scheduler retrying another."""

    def test_terminal_on_one_lock_and_transient_on_the_other_keeps_retrying_the_other(self):
        # Back drops the PIN (a terminal rejection), Side's set times out.
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True, reject_pins={12: {self.PIN}})
        gateway.set_times_out_on = {13}
        code = door_codes_uc.create_door_code(
            user=self.user, raw_code=self.PIN, lock_entity_ids=[self.BACK, self.SIDE], zwavejs=gateway
        )
        back, side = self._assignment(code, self.BACK), self._assignment(code, self.SIDE)
        code.refresh_from_db()
        self.assertEqual(code.push_state, FAILED)
        self.assertEqual(_lock_state(back)[:2], (None, FAILED))
        self.assertEqual(_lock_state(side)[:3], (None, PENDING, 1))

        # Side still down: only Side is tried, and the code stays failed for Back.
        gateway.invoke_calls.clear()
        self.assertEqual(self._tick(gateway), 1)
        self.assertEqual(self._nodes_sent(gateway), [13])
        self.assertEqual(_lock_state(side)[:3], (None, PENDING, 2))

        # Side back: it's pushed, and Back is still never touched.
        gateway.set_times_out_on = set()
        gateway.invoke_calls.clear()
        self.assertEqual(self._tick(gateway), 1)
        self.assertEqual(_lock_state(side), (1, PUSHED, 0, "", False))
        self.assertEqual(_lock_state(back)[:2], (None, FAILED))
        self.assertNotIn(12, [c["node_id"] for c in gateway.invoke_calls])
        code.refresh_from_db()
        self.assertEqual(code.push_state, FAILED)
        self.assertIn(f"{self.BACK}: ", code.last_push_error)
        self.assertNotIn(self.SIDE, code.last_push_error)

        # Nothing left for the scheduler.
        gateway.invoke_calls.clear()
        self.assertEqual(self._tick(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

        # Retry re-arms Back once the lock takes the PIN.
        gateway._reject_pins = {}
        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))
        self.assertEqual(self._nodes_sent(gateway), [12])
        code.refresh_from_db()
        self.assertEqual((code.push_state, code.last_push_error), (PUSHED, ""))

    def test_slot_recorded_for_another_code_only_fails_that_lock(self):
        # PR #190's IntegrityError path: another code's assignment takes Back's
        # slot during the push. Side only timed out, so the scheduler retries it.
        other = self._code()
        other_back = self._lock(other, self.BACK)

        class ConcurrentWriterGateway(PerNodeGateway):
            def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
                if (node_id, command_class, method_name) == (12, 99, "set") and other_back.slot_index is None:
                    other_back.slot_index = args[0]
                    DoorCodeLockAssignment.objects.filter(id=other_back.id).update(slot_index=args[0])
                return super().invoke_cc_api(
                    node_id=node_id,
                    command_class=command_class,
                    method_name=method_name,
                    args=args,
                    timeout_seconds=timeout_seconds,
                )

        gateway = ConcurrentWriterGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.set_times_out_on = {13}
        code = door_codes_uc.create_door_code(
            user=self.user, raw_code="8642", lock_entity_ids=[self.BACK, self.SIDE], zwavejs=gateway
        )
        back, side = self._assignment(code, self.BACK), self._assignment(code, self.SIDE)
        self.assertEqual(_lock_state(back)[:2], (None, FAILED))
        self.assertIn("recorded for another door code", back.last_push_error)
        self.assertEqual(_lock_state(side)[:2], (None, PENDING))

        gateway.set_times_out_on = set()
        gateway.invoke_calls.clear()
        self._tick(gateway)

        self.assertEqual(self._nodes_sent(gateway), [13])
        self.assertEqual(_lock_state(side)[:2], (1, PUSHED))
        self.assertEqual(_lock_state(back)[:2], (None, FAILED))
        code.refresh_from_db()
        self.assertEqual(code.push_state, FAILED)


class PerLockCapTests(_PerLockTestBase):
    """Issue #126: each lock's own count goes against ``door_codes.push_max_attempts``."""

    def test_one_locks_success_doesnt_reset_another_locks_count(self):
        code = self._code(push_attempt_count=0)
        back = self._lock(code, self.BACK)
        side = self._lock(code, self.SIDE, push_attempt_count=23)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.set_times_out_on = {13}

        self._tick(gateway)

        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))
        slot_index, state, count, error, _ = _lock_state(side)
        self.assertEqual((slot_index, state, count), (None, FAILED, 24))
        self.assertIn("ZwavejsCommandError", error)
        self.assertEqual(self._cap_events(code), [(self.SIDE, 24)])
        code.refresh_from_db()
        self.assertEqual(code.push_state, FAILED)
        self.assertIn(f"{self.SIDE}: Push gave up after 24 attempts", code.last_push_error)

    def test_a_pending_lock_already_over_the_cap_is_failed_without_being_tried_and_retry_rearms_it(self):
        code = self._code()
        back = self._lock(code, self.BACK, push_attempt_count=30)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)

        self.assertEqual(self._tick(gateway), 0)

        self.assertEqual(gateway.invoke_calls, [])
        # No error of its own, so the code says it gave up.
        self.assertEqual(_lock_state(back), (None, FAILED, 30, "", False))
        self.assertEqual(self._cap_events(code), [(self.BACK, 30)])
        code.refresh_from_db()
        self.assertEqual(
            (code.push_state, code.last_push_error), (FAILED, f"{self.BACK}: Push gave up after 30 attempts")
        )
        # Not swept twice.
        self._tick(gateway)
        self.assertEqual(len(self._cap_events(code)), 1)

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))
        code.refresh_from_db()
        self.assertEqual(code.push_state, PUSHED)

    def test_a_lowered_cap_fails_a_lock_already_past_it(self):
        code = self._code()
        back = self._lock(code, self.BACK, push_attempt_count=5)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)

        with patch("locks.tasks._get_push_max_attempts", return_value=3):
            self._tick(gateway)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(_lock_state(back)[:3], (None, FAILED, 5))

    def test_retry_resets_a_pending_lock_over_the_cap_before_the_sweep_gets_it(self):
        code = self._code()
        back = self._lock(code, self.BACK, push_attempt_count=30)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.set_times_out_on = {12}

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        # Back to 0 first, then this push's timeout counts once.
        self.assertEqual(_lock_state(back)[:3], (None, PENDING, 1))

    def test_the_cap_leaves_a_lock_of_an_expired_code_pending(self):
        # The ~expired half of the sweep's filter: the validity task retires it, not the cap.
        code = self._code(end_at=timezone.now() - timedelta(minutes=1))
        back = self._lock(code, self.BACK, push_attempt_count=30)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)

        self._tick(gateway)
        lock_push_uc.sweep_push_cap(now=timezone.now(), max_attempts=24)

        self.assertEqual(_lock_state(back)[:3], (None, PENDING, 30))
        self.assertEqual(self._cap_events(code), [])
        self.assertEqual(gateway.invoke_calls, [])

    def test_the_cap_leaves_a_lock_of_a_code_that_hasnt_started_pending(self):
        code = self._code(start_at=timezone.now() + timedelta(hours=1))
        back = self._lock(code, self.BACK, push_attempt_count=30)

        lock_push_uc.sweep_push_cap(now=timezone.now(), max_attempts=24)

        self.assertEqual(_lock_state(back)[:3], (None, PENDING, 30))

    def test_the_cap_uses_the_now_it_is_given(self):
        # The tick's now, so a code whose end_at passes mid-tick errs toward pending (PR #195 review).
        now = timezone.now()
        code = self._code(end_at=now + timedelta(seconds=30))
        back = self._lock(code, self.BACK, push_attempt_count=30)

        lock_push_uc.sweep_push_cap(now=now + timedelta(minutes=1), max_attempts=24)
        self.assertEqual(_lock_state(back)[1], PENDING)

        lock_push_uc.sweep_push_cap(now=now, max_attempts=24)
        self.assertEqual(_lock_state(back)[1], FAILED)

    def test_the_cap_leaves_a_lock_being_removed_alone(self):
        code = self._code()
        self._lock(code, self.BACK, slot_index=1, push_state=PUSHED)
        side = self._lock(code, self.SIDE, slot_index=2, schedule_pending=True, push_attempt_count=30)
        lock_push_uc._create_clear_failed_event(
            door_code=code,
            failure=ClearFailure(lock_entity_id=self.SIDE, slot_index=2, reason="timeout", removing=True),
        )

        lock_push_uc.sweep_push_cap(now=timezone.now(), max_attempts=24)

        self.assertEqual(_lock_state(side)[1], PENDING)
        self.assertEqual(self._cap_events(code), [])


class SchedulePendingTests(_PerLockTestBase):
    """Issue #123: the slot goes on record before the schedule, and the scheduler sends only the schedule."""

    def _scheduled_code(self, gateway) -> DoorCode:
        return door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b0011111,
            window_start=time(9, 0),
            window_end=time(17, 0),
            lock_entity_ids=[self.BACK],
            zwavejs=gateway,
        )

    def test_a_schedule_timeout_keeps_the_slot_and_the_next_tick_sends_only_the_schedule(self):
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.schedule_fails_on = {12: ZwavejsCommandError(TIMEOUT)}
        code = self._scheduled_code(gateway)

        back = self._assignment(code, self.BACK)
        slot_index, state, count, error, schedule_pending = _lock_state(back)
        self.assertEqual((slot_index, state, count, schedule_pending), (1, PENDING, 1, True))
        self.assertIn("Schedule not applied", error)
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        code.refresh_from_db()
        self.assertEqual(code.push_state, PENDING)

        gateway.schedule_fails_on = {}
        gateway.invoke_calls.clear()
        self.assertEqual(self._tick(gateway), 1)

        self.assertEqual([c for c in gateway.invoke_calls if c["command_class"] == 99], [])
        schedules = [c for c in gateway.invoke_calls if c["method_name"] == "setDailyRepeatingSchedule"]
        self.assertEqual(len(schedules), 5)
        self.assertEqual({c["args"][0]["userId"] for c in schedules}, {1})
        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))
        code.refresh_from_db()
        self.assertEqual((code.push_state, code.last_push_error), (PUSHED, ""))
        event = DoorCodeEvent.objects.filter(door_code=code, metadata__action="schedule_pushed").get()
        self.assertEqual((event.lock_entity_id, event.metadata["slot_index"]), (self.BACK, 1))

    def test_delete_while_the_schedule_is_pending_clears_the_slot(self):
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.schedule_fails_on = {12: ZwavejsCommandError(TIMEOUT)}
        code = self._scheduled_code(gateway)
        self.assertTrue(self._assignment(code, self.BACK).schedule_pending)
        gateway.invoke_calls.clear()

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._calls(gateway, "clear"), [(12, [1])])
        self.assertEqual(self._lock_codes(gateway, 12), {})

    def test_a_process_dying_between_the_slot_and_the_schedule_leaves_it_to_the_scheduler(self):
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        code = self._code(
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b1,
            window_start=time(9, 0),
            window_end=time(17, 0),
        )
        back = self._lock(code, self.BACK)

        with (
            patch.object(lock_push_uc, "_push_daily_repeating_schedule", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        self.assertEqual(_lock_state(back), (1, PENDING, 0, "", True))
        # The slot is tracked, so the #190 marker went with the slot's commit.
        self.assertFalse(DoorCodeEvent.objects.filter(door_code=code, metadata__action="push_unconfirmed").exists())
        code.refresh_from_db()
        self.assertEqual(code.push_state, PENDING)

        gateway.invoke_calls.clear()
        self._tick(gateway)

        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._nodes_sent(gateway, 78, "setDailyRepeatingSchedule"), [12])
        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))
        code.refresh_from_db()
        self.assertEqual(code.push_state, PUSHED)

    def test_a_terminal_schedule_failure_keeps_the_slot_and_retry_sends_only_the_schedule(self):
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.schedule_fails_on = {12: ZwavejsCommandValidationError("bad schedule args")}
        code = self._scheduled_code(gateway)

        back = self._assignment(code, self.BACK)
        self.assertEqual(_lock_state(back)[:2], (1, FAILED))
        self.assertTrue(back.schedule_pending)
        code.refresh_from_db()
        self.assertEqual(code.push_state, FAILED)
        # Failed, so the scheduler leaves it to Retry.
        gateway.invoke_calls.clear()
        self.assertEqual(self._tick(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

        gateway.schedule_fails_on = {}
        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(len(self._nodes_sent(gateway, 78, "setDailyRepeatingSchedule")), 5)
        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))

    def test_a_schedule_that_lands_marks_the_lock_pushed_in_one_push(self):
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)

        code = self._scheduled_code(gateway)

        self.assertEqual(_lock_state(self._assignment(code, self.BACK)), (1, PUSHED, 0, "", False))
        actions = list(
            DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
            .order_by("id")
            .values_list("metadata__action", flat=True)
        )
        self.assertEqual(actions, ["pushed", "schedule_pushed"])

    def test_a_schedule_only_resend_with_a_bad_window_is_terminal_and_sends_nothing(self):
        code = self._code(
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b1,
            window_start=time(17, 0),
            window_end=time(9, 0),
        )
        back = self._lock(code, self.BACK, slot_index=1, schedule_pending=True)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)

        with self.assertRaises(lock_push_uc.InvalidPin):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(_lock_state(back)[:2], (1, FAILED))
        self.assertTrue(back.schedule_pending)


class NormalizeAssignmentPushStateTests(_PerLockTestBase):
    """PR #195 review: per-lock state that drifted from its slot is repaired at the start of each tick."""

    def _normalize(self) -> int:
        return lock_push_uc.normalize_assignment_push_state()

    def test_a_slot_that_isnt_pushed_without_a_pending_schedule_is_pushed(self):
        for state in (PENDING, FAILED):
            with self.subTest(state=state):
                code = self._code(push_state=PENDING)
                back = self._lock(
                    code, self.BACK, slot_index=1, push_state=state, push_attempt_count=3, last_push_error="x"
                )

                self._normalize()

                self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))
                code.refresh_from_db()
                self.assertEqual(code.push_state, PUSHED)
                code.delete()

    def test_no_slot_with_pushed_or_a_pending_schedule_is_pending(self):
        code = self._code(push_state=PUSHED)
        back = self._lock(code, self.BACK, push_state=PUSHED, push_attempt_count=2)
        side = self._lock(code, self.SIDE, schedule_pending=True)

        self._normalize()

        self.assertEqual(_lock_state(back), (None, PENDING, 2, "", False))
        self.assertEqual(_lock_state(side), (None, PENDING, 0, "", False))
        code.refresh_from_db()
        self.assertEqual(code.push_state, PENDING)

    def test_a_stale_failed_lock_on_an_active_code_that_isnt_failed_is_rederived_from_the_code(self):
        # Old code pushed or reset the code after a rollback, but not its locks.
        code = self._code(push_state=PENDING, push_attempt_count=2)
        back = self._lock(code, self.BACK, push_state=FAILED, push_attempt_count=24, last_push_error="rejected")
        side = self._lock(code, self.SIDE, slot_index=3, push_state=FAILED, push_attempt_count=24)

        self._normalize()

        self.assertEqual(_lock_state(back)[:3], (None, PENDING, 2))
        self.assertEqual(_lock_state(side), (3, PUSHED, 0, "", False))

    def test_failed_locks_of_a_failed_or_inactive_code_are_left_alone(self):
        failed_code = self._code(push_state=FAILED)
        failed_lock = self._lock(failed_code, self.BACK, push_state=FAILED, push_attempt_count=4)
        inactive = self._code(is_active=False, push_state=PUSHED)
        inactive_lock = self._lock(inactive, self.BACK, push_state=FAILED, push_attempt_count=4)

        self.assertEqual(self._normalize(), 0)

        self.assertEqual(_lock_state(failed_lock)[:3], (None, FAILED, 4))
        self.assertEqual(_lock_state(inactive_lock)[:3], (None, FAILED, 4))

    def test_valid_states_are_left_alone(self):
        code = self._code(push_state=PENDING)
        rows = [
            self._lock(code, self.BACK, slot_index=1, push_state=PUSHED),
            self._lock(code, self.SIDE, slot_index=2, schedule_pending=True, push_attempt_count=1),
            self._lock(code, self.FRONT),
        ]
        before = [_lock_state(row) for row in rows]

        self.assertEqual(self._normalize(), 0)

        self.assertEqual([_lock_state(row) for row in rows], before)

    def test_the_scheduler_normalizes_before_it_picks_codes(self):
        # A lock with no slot left pushed would never be picked up.
        code = self._code(push_state=PUSHED)
        back = self._lock(code, self.BACK, push_state=PUSHED)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)

        self.assertEqual(self._tick(gateway), 1)

        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))


class BackfilledFailedCodeBeforeItsStartTests(_PerLockTestBase):
    """PR #195 review: a not-started code the 0010 backfill marked failed still goes on its locks at its start."""

    def test_it_goes_on_its_locks_at_its_start(self):
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        start = timezone.now() + timedelta(hours=1)
        code = self._code(
            start_at=start,
            push_state=FAILED,
            push_attempt_count=7,
            last_push_attempt_at=timezone.now() - timedelta(hours=1),
            last_push_error="Lock rejected the code",
        )
        back = self._lock(code, self.BACK)
        importlib.import_module("locks.migrations.0010_backfill_assignment_push_state")._backfill_assignment_push_state(
            django_apps, None
        )
        self.assertEqual(_lock_state(back)[:3], (None, FAILED, 7))

        # Nothing goes on before the start.
        self._enforce(gateway)
        self._tick(gateway)
        self.assertEqual(gateway.invoke_calls, [])

        DoorCode.objects.filter(id=code.id).update(start_at=timezone.now() - timedelta(seconds=5))
        self._enforce(gateway)

        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))
        code.refresh_from_db()
        self.assertEqual(code.push_state, PUSHED)


class RefreshPushStateMatrixTests(_PerLockTestBase):
    """The one rollup writer against every guarantee it took over (PRs #144, #157, #165, #167, #183, issue #126)."""

    def _clear_failure(self, code: DoorCode, lock_entity_id: str, slot_index: int, **flags) -> None:
        lock_push_uc._create_clear_failed_event(
            door_code=code,
            failure=ClearFailure(lock_entity_id=lock_entity_id, slot_index=slot_index, reason="timeout", **flags),
        )

    def _refresh(self, code: DoorCode) -> tuple[str, str, int]:
        lock_push_uc.refresh_push_state(door_code=code)
        code.refresh_from_db()
        return code.push_state, code.last_push_error, code.push_attempt_count

    def _case(self, *, locks=(), failures=(), **code_fields) -> tuple[str, str, int]:
        code = self._code(push_state=code_fields.pop("push_state", PUSHED), **code_fields)
        for lock_entity_id, fields in locks:
            self._lock(code, lock_entity_id, **fields)
        for lock_entity_id, slot_index, flags in failures:
            self._clear_failure(code, lock_entity_id, slot_index, **flags)
        return self._refresh(code)

    def test_matrix(self):
        future = timezone.now() + timedelta(hours=1)
        clear_back = (self.BACK, 1, {})
        cases = {
            # PR #157: no locks and nothing to clear.
            "active, no locks": ({"push_attempt_count": 5}, (PENDING, "", 0)),
            "inactive, no locks": ({"is_active": False, "push_state": FAILED, "last_push_error": "x"}, (PUSHED, "", 0)),
            # PR #144: an inactive code's clear failure keeps it pending, and at the cap failed.
            "inactive, clear failure": (
                {"is_active": False, "locks": [(self.BACK, {"slot_index": 1})], "failures": [clear_back]},
                (PENDING, "Couldn't clear slot 1", 0),
            ),
            "inactive, clear failure at the cap": (
                {
                    "is_active": False,
                    "push_attempt_count": 24,
                    "locks": [(self.BACK, {"slot_index": 1})],
                    "failures": [clear_back],
                },
                (FAILED, "Couldn't clear slot 1", 24),
            ),
            # PR #167: an inactive manual code's tracked slot is outstanding, a synced one's isn't.
            "inactive manual, tracked slot": (
                {"is_active": False, "locks": [(self.BACK, {"slot_index": 1, "push_state": PUSHED})]},
                (PENDING, "", 0),
            ),
            "inactive synced, tracked slot": (
                {
                    "is_active": False,
                    "source": DoorCode.Source.SYNCED,
                    "locks": [(self.BACK, {"slot_index": 1, "push_state": PUSHED})],
                },
                (PUSHED, "", 0),
            ),
            "inactive, slots cleared": ({"is_active": False, "locks": [(self.BACK, {})]}, (PUSHED, "", 0)),
            # PR #183: before its start it's scheduled, a slot it holds is withdrawn, a capped clear fails it.
            "not started, no slot": (
                {"start_at": future, "locks": [(self.BACK, {"push_state": FAILED, "last_push_error": "x"})]},
                (PENDING, "", 0),
            ),
            "not started, holds a slot": (
                {"start_at": future, "locks": [(self.BACK, {"slot_index": 1, "push_state": PUSHED})]},
                (PENDING, "", 0),
            ),
            "not started, clear failure at the cap": (
                {
                    "start_at": future,
                    "push_attempt_count": 24,
                    "locks": [(self.BACK, {"slot_index": 1})],
                    "failures": [clear_back],
                },
                (FAILED, "Couldn't clear slot 1", 24),
            ),
            # Issue #126: active and started, the locks decide.
            "every lock pushed": (
                {
                    "push_state": FAILED,
                    "push_attempt_count": 3,
                    "locks": [
                        (self.BACK, {"slot_index": 1, "push_state": PUSHED}),
                        (self.SIDE, {"slot_index": 2, "push_state": PUSHED}),
                    ],
                },
                (PUSHED, "", 0),
            ),
            "one failed, one still pending": (
                {
                    "locks": [
                        (self.BACK, {"push_state": FAILED, "last_push_error": "rejected"}),
                        (self.SIDE, {"push_attempt_count": 2, "last_push_error": "timeout"}),
                    ]
                },
                (FAILED, f"{self.BACK}: rejected; {self.SIDE}: timeout", 0),
            ),
            "one pending": ({"locks": [(self.BACK, {})]}, (PENDING, "", 0)),
            "schedule pending": (
                {"locks": [(self.BACK, {"slot_index": 1, "schedule_pending": True})]},
                (PENDING, "", 0),
            ),
            # PR #144: a clear failure never lets it show pushed, and at the cap it's failed.
            "pushed with a clear failure": (
                {"locks": [(self.BACK, {"slot_index": 1, "push_state": PUSHED})], "failures": [clear_back]},
                (PENDING, "Couldn't clear slot 1", 0),
            ),
            "pushed with a clear failure at the cap": (
                {
                    "push_attempt_count": 24,
                    "locks": [(self.BACK, {"slot_index": 1, "push_state": PUSHED})],
                    "failures": [clear_back],
                },
                (FAILED, "Couldn't clear slot 1", 24),
            ),
            # Issue #151: a lock being dropped doesn't count, but its clear keeps the code pending.
            "failed lock being removed": (
                {
                    "locks": [
                        (self.BACK, {"slot_index": 1, "push_state": PUSHED}),
                        (self.SIDE, {"slot_index": 2, "push_state": FAILED, "schedule_pending": True}),
                    ],
                    "failures": [(self.SIDE, 2, {"removing": True})],
                },
                (PENDING, "Couldn't clear slot 2", 0),
            ),
            # PR #165: a code lock sync imported is on the lock.
            "synced, imported slot": (
                {"source": DoorCode.Source.SYNCED, "locks": [(self.BACK, {"slot_index": 1, "push_state": PUSHED})]},
                (PUSHED, "", 0),
            ),
        }
        for name, (fields, (state, error, count)) in cases.items():
            with self.subTest(name):
                got_state, got_error, got_count = self._case(**fields)
                self.assertEqual((got_state, got_count), (state, count))
                if error:
                    self.assertTrue(got_error.startswith(error), got_error)
                else:
                    self.assertEqual(got_error, "")
                DoorCode.objects.all().delete()

    def test_clear_failures_lead_the_error_then_each_lock(self):
        code = self._code(push_state=PENDING)
        self._lock(code, self.BACK, slot_index=1, push_state=PUSHED)
        self._lock(code, self.SIDE, push_attempt_count=1, last_push_error="LockUnreachable: timed out")
        self._clear_failure(code, self.BACK, 1)

        _state, error, _count = self._refresh(code)

        self.assertEqual(
            error,
            f"Couldn't clear slot 1 on {self.BACK}, it may still hold the PIN (timeout); "
            f"{self.SIDE}: LockUnreachable: timed out",
        )

    def test_the_inactive_rollup_doesnt_land_once_the_code_is_back_on(self):
        # PR #167 review: the update that turned it on owns its state.
        code = self._code(is_active=True, push_state=PENDING, last_push_error="LockUnreachable: timed out")
        self._lock(code, self.BACK)

        self.assertIsNone(lock_push_uc.refresh_push_state(door_code=code, only_if_active=False))

        code.refresh_from_db()
        self.assertEqual(code.last_push_error, "LockUnreachable: timed out")


class PerLockSerializerTests(_PerLockTestBase):
    """Issue #126: each lock's push state is in the API, never a PIN."""

    def test_each_lock_has_its_own_push_fields_and_no_pin(self):
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True, reject_pins={12: {self.PIN}})
        gateway.schedule_fails_on = {13: ZwavejsCommandError(TIMEOUT)}
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b1,
            window_start=time(9, 0),
            window_end=time(17, 0),
            lock_entity_ids=[self.BACK, self.SIDE],
            zwavejs=gateway,
        )
        fetched = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)

        for serializer in (DoorCodeSerializer, DoorCodePushSerializer):
            with self.subTest(serializer=serializer.__name__):
                data = serializer(fetched).data
                by_lock = {entry["lock_entity_id"]: entry for entry in data["lock_slot_assignments"]}
                back, side = by_lock[self.BACK], by_lock[self.SIDE]
                self.assertEqual(
                    (back["slot_index"], back["push_state"], back["push_attempt_count"], back["schedule_pending"]),
                    (None, FAILED, 1, False),
                )
                self.assertIn("reads back empty", back["last_push_error"])
                self.assertEqual(
                    (side["slot_index"], side["push_state"], side["push_attempt_count"], side["schedule_pending"]),
                    (1, PENDING, 1, True),
                )
                self.assertIn("Schedule not applied", side["last_push_error"])
                self.assertIsNotNone(side["last_push_attempt_at"])
                # The code-level fields stay the rollup.
                self.assertEqual(data["push_state"], FAILED)
                for entry in (back, side):
                    payload = json.dumps({k: v for k, v in entry.items() if k != "last_push_attempt_at"})
                    self.assertNotIn(self.PIN, payload)
                    self.assertNotIn("encrypted_pin", payload)


class LockOrderTests(_PerLockTestBase):
    """PR #195 review: writers of a code and its assignments take the code row first, so they can't deadlock."""

    def _record_row_locks_and_writes(self):
        events: list[tuple[str, object, int]] = []
        real_select_for_update = QuerySet.select_for_update
        real_update = QuerySet.update
        real_delete = DoorCode.delete

        def select_for_update(queryset, *args, **kwargs):
            events.append(("lock", queryset.model, len(connection.atomic_blocks)))
            return real_select_for_update(queryset, *args, **kwargs)

        def update(queryset, **kwargs):
            events.append(("update", queryset.model, len(connection.atomic_blocks)))
            return real_update(queryset, **kwargs)

        def delete(instance, *args, **kwargs):
            events.append(("delete", DoorCode, len(connection.atomic_blocks)))
            return real_delete(instance, *args, **kwargs)

        patches = [
            patch.object(QuerySet, "select_for_update", select_for_update),
            patch.object(QuerySet, "update", update),
            patch.object(DoorCode, "delete", delete),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return events

    def test_delete_takes_the_code_row_before_it_deletes_the_assignments(self):
        # code.delete() deletes the assignments, then the code row. The cap sweep
        # takes the code row, then updates assignments. On Postgres, delete taking
        # the code row first inside its transaction means whichever of the two
        # gets the code row first finishes before the other touches an assignment.
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        events = self._record_row_locks_and_writes()

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        deletes = [index for index, event in enumerate(events) if event[0] == "delete"]
        self.assertEqual(len(deletes), 1)
        lock = max(index for index, event in enumerate(events[: deletes[0]]) if event[:2] == ("lock", DoorCode))
        # In the same transaction as the delete, with nothing written in between.
        self.assertEqual(events[lock][2], events[deletes[0]][2])
        self.assertEqual([event for event in events[lock + 1 : deletes[0]] if event[0] == "update"], [])

    def test_the_cap_sweep_takes_the_code_row_before_its_assignments(self):
        code = self._code()
        self._lock(code, self.BACK, push_attempt_count=30)
        events = self._record_row_locks_and_writes()

        lock_push_uc.sweep_push_cap(now=timezone.now(), max_attempts=24)

        first_lock = events.index(next(event for event in events if event[:2] == ("lock", DoorCode)))
        first_assignment_write = events.index(
            next(event for event in events if event[:2] == ("update", DoorCodeLockAssignment))
        )
        self.assertLess(first_lock, first_assignment_write)
        self.assertEqual(_lock_state(DoorCodeLockAssignment.objects.get(door_code=code))[1], FAILED)

    def test_the_push_failure_takes_the_code_row_before_the_lock(self):
        code = self._code()
        self._lock(code, self.BACK)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.set_times_out_on = {12}
        events = self._record_row_locks_and_writes()

        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        first_lock = events.index(next(event for event in events if event[:2] == ("lock", DoorCode)))
        first_assignment_write = events.index(
            next(event for event in events if event[:2] == ("update", DoorCodeLockAssignment))
        )
        self.assertLess(first_lock, first_assignment_write)

    def test_a_terminal_push_failure_is_still_raised(self):
        code = self._code()
        self._lock(code, self.BACK)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True, admin_code=self.PIN)

        with self.assertRaises(LockPushFailed):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        self.assertEqual(_lock_state(self._assignment(code, self.BACK))[:2], (None, FAILED))


class SuccessBlockRestoreTests(_PerLockTestBase):
    """PR #195 review: a success block that rolls back for any reason puts the in-memory push fields back."""

    def test_any_exception_restores_the_snapshot(self):
        code = self._code(push_state=PENDING, push_attempt_count=2, last_push_error="old")
        self._lock(code, self.BACK)
        before = (code.push_state, code.last_push_attempt_at, code.last_push_error, code.push_attempt_count)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)

        real_refresh = lock_push_uc.refresh_push_state

        def refresh_then_fail(**kwargs):
            real_refresh(**kwargs)
            raise RuntimeError("boom")

        with patch.object(lock_push_uc, "refresh_push_state", refresh_then_fail), self.assertRaises(RuntimeError):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        self.assertEqual(
            (code.push_state, code.last_push_attempt_at, code.last_push_error, code.push_attempt_count), before
        )
        self.assertIsNone(self._assignment(code, self.BACK).slot_index)


class PendingRemovalTests(_PerLockTestBase):
    """PR #196 review: a lock the code is being dropped from never picks the code for a push."""

    def _code_dropping_side(self, *, side_state: str = PENDING, clear_count: int = 0) -> DoorCode:
        """Back is on the lock, Side is being dropped with its schedule still pending and its clear failing."""
        code = self._code(push_attempt_count=clear_count)
        self._lock(code, self.BACK, slot_index=1, push_state=PUSHED)
        self._lock(code, self.SIDE, slot_index=2, push_state=side_state, schedule_pending=True)
        lock_push_uc._create_clear_failed_event(
            door_code=code,
            failure=ClearFailure(lock_entity_id=self.SIDE, slot_index=2, reason="timeout", removing=True),
        )
        # What the clear that failed left the code at.
        lock_push_uc.refresh_push_state(door_code=code)
        return code

    def test_a_lock_being_removed_with_its_schedule_pending_doesnt_run_the_clears_past_the_cap(self):
        # The probe: the code's clear-retry count is at the cap and every tick used to clear again (25, 26, 27).
        code = self._code_dropping_side(clear_count=24)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.clear_fails_on = {13}

        for _tick in range(3):
            self._tick(gateway)

        self.assertEqual(gateway.invoke_calls, [])
        code.refresh_from_db()
        self.assertEqual((code.push_state, code.push_attempt_count), (FAILED, 24))
        self.assertEqual(_lock_state(self._assignment(code, self.SIDE))[:2], (2, PENDING))

    def test_under_the_cap_only_the_clear_is_retried(self):
        code = self._code_dropping_side()
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.clear_fails_on = {13}

        self._tick(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(13, [2])])
        self.assertEqual(self._nodes_sent(gateway, 78, "setDailyRepeatingSchedule"), [])
        code.refresh_from_db()
        self.assertEqual(code.push_attempt_count, 1)

    def test_the_normalizer_leaves_a_failed_lock_being_removed_failed(self):
        # The rollup ignores it, so its code isn't failed, which isn't the stale case.
        code = self._code_dropping_side(side_state=FAILED)
        code.refresh_from_db()
        self.assertEqual(code.push_state, PENDING)

        lock_push_uc.normalize_assignment_push_state()

        self.assertEqual(_lock_state(self._assignment(code, self.SIDE))[:2], (2, FAILED))


class ScheduleAfterAFailedClearTests(_PerLockTestBase):
    """PR #196 review: a slot whose clear failed may still hold the old PIN, so its schedule isn't resent."""

    def test_a_pin_change_whose_clear_failed_doesnt_give_the_old_pin_the_window(self):
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.schedule_fails_on = {12: ZwavejsCommandError(TIMEOUT)}
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b1,
            window_start=time(9, 0),
            window_end=time(17, 0),
            lock_entity_ids=[self.BACK],
            zwavejs=gateway,
        )
        back = self._assignment(code, self.BACK)
        self.assertEqual(_lock_state(back)[:2], (1, PENDING))
        self.assertTrue(back.schedule_pending)

        # The schedule would go through now, but the PIN change can't clear slot 1.
        gateway.schedule_fails_on = {}
        gateway.clear_fails_on = {12}
        gateway.invoke_calls.clear()
        code = self._update(code, gateway, {"code": "5555"})

        self.assertEqual(self._nodes_sent(gateway, 78, "setDailyRepeatingSchedule"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(_lock_state(back)[:2], (1, PENDING))
        self.assertTrue(back.schedule_pending)
        self.assertEqual(code.push_state, PENDING)
        # And straight to the lock, nothing goes out and nothing is counted.
        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)
        self.assertEqual(self._nodes_sent(gateway, 78, "setDailyRepeatingSchedule"), [])
        self.assertEqual(_lock_state(back)[:3], (1, PENDING, 1))

        # The clear retry frees the slot and the new PIN goes on with its schedule.
        gateway.clear_fails_on = set()
        self._tick(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: "5555"})
        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))
        self.assertEqual(self._nodes_sent(gateway, 78, "setDailyRepeatingSchedule"), [12])


class IncludeFailedTests(_PerLockTestBase):
    """Only Retry pushes a lock that's ``failed``."""

    def test_a_failed_lock_is_only_pushed_with_include_failed(self):
        code = self._code(push_state=FAILED)
        back = self._lock(code, self.BACK, push_state=FAILED, last_push_error="rejected")
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)

        lock_push_uc.push_door_code_to_assigned_locks(door_code=self._fresh(code), zwavejs=gateway)
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(_lock_state(back)[:2], (None, FAILED))

        lock_push_uc.push_door_code_to_assigned_locks(door_code=self._fresh(code), zwavejs=gateway, include_failed=True)
        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))

    def test_retry_pushes_a_lock_that_failed_again_after_it_was_rearmed(self):
        # Ie another push failed it terminally between Retry's re-arm and its push.
        code = self._code(push_state=FAILED)
        back = self._lock(code, self.BACK, push_state=FAILED)
        gateway = PerNodeGateway(usersNumber=5, cache_updates_on_set=True)
        real_rearm = lock_push_uc.rearm_failed_locks

        def rearm_then_fail_again(**kwargs):
            changed = real_rearm(**kwargs)
            DoorCodeLockAssignment.objects.filter(id=back.id).update(push_state=FAILED)
            return changed

        with patch.object(lock_push_uc, "rearm_failed_locks", rearm_then_fail_again):
            door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))

    @staticmethod
    def _fresh(code: DoorCode) -> DoorCode:
        return DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)


class LockSyncPerLockTests(EncryptionTestMixin, APITestCase):
    """PR #196 review: lock sync keeps a pending schedule and refreshes the codes it changes."""

    LOCK = sync_tests.LockConfigSyncReconcileTests.LOCK  # node 5
    setUp = sync_tests.LockConfigSyncReconcileTests.setUp
    _sync = sync_tests.LockConfigSyncReconcileTests._sync
    _manual_code = sync_tests.LockConfigSyncReconcileTests._manual_code
    _slot = staticmethod(sync_tests.LockConfigSyncReconcileTests._slot)

    def test_a_sync_leaves_a_lock_whose_schedule_is_pending_for_the_scheduler(self):
        # The probe: the PIN is in slot 1 but its CC 78 schedule never landed.
        code = self._manual_code(pin="4321", slot_index=1)
        DoorCode.objects.filter(id=code.id).update(
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=31,
            window_start=time(9, 0),
            window_end=time(17, 0),
            push_state=PENDING,
        )
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        DoorCodeLockAssignment.objects.filter(id=assignment.id).update(push_state=PENDING, schedule_pending=True)

        body = self._sync(sync_tests.SlotGateway({1: (1, "4321")}))

        slot = self._slot(body, 1)
        self.assertEqual(slot["action"], "skipped")
        self.assertIn("schedule_pending", slot["warnings"])
        code.refresh_from_db()
        self.assertEqual((code.source, code.days_of_week), (DoorCode.Source.MANUAL, 31))
        self.assertEqual(_lock_state(assignment), (1, PENDING, 0, "", True))

        # So the next tick still sends the schedule, and only the schedule.
        gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)
        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            from locks.tasks import push_pending_door_codes

            push_pending_door_codes()

        self.assertEqual([c for c in gateway.invoke_calls if c["command_class"] == 99], [])
        schedules = [c for c in gateway.invoke_calls if c["method_name"] == "setDailyRepeatingSchedule"]
        self.assertEqual({c["args"][0]["userId"] for c in schedules}, {1})
        self.assertEqual(len(schedules), 5)
        self.assertEqual(_lock_state(assignment), (1, PUSHED, 0, "", False))

    def test_a_sync_refreshes_the_rollup_of_a_code_it_converts(self):
        code = self._manual_code(pin="4321", slot_index=1)
        DoorCode.objects.filter(id=code.id).update(push_state=PENDING, last_push_error="LockUnreachable: timed out")
        DoorCodeLockAssignment.objects.filter(door_code=code).update(push_state=PENDING)

        self._sync(sync_tests.SlotGateway({1: (1, "4321")}))

        code.refresh_from_db()
        self.assertEqual(code.source, DoorCode.Source.SYNCED)
        self.assertEqual((code.push_state, code.last_push_error), (PUSHED, ""))

    def test_releasing_an_inactive_synced_codes_slot_takes_the_code_row_first(self):
        self._sync(sync_tests.SlotGateway({1: (1, "1234")}))
        assignment = DoorCodeLockAssignment.objects.get(lock_entity_id=self.LOCK)
        DoorCode.objects.filter(id=assignment.door_code_id).update(is_active=False)
        events: list[tuple[str, object]] = []
        real_select_for_update = QuerySet.select_for_update
        real_save = DoorCodeLockAssignment.save

        def select_for_update(queryset, *args, **kwargs):
            events.append(("lock", queryset.model))
            return real_select_for_update(queryset, *args, **kwargs)

        def save(instance, *args, **kwargs):
            events.append(("save", DoorCodeLockAssignment))
            return real_save(instance, *args, **kwargs)

        with (
            patch.object(QuerySet, "select_for_update", select_for_update),
            patch.object(DoorCodeLockAssignment, "save", save),
        ):
            self._sync(sync_tests.SlotGateway({1: (0, None)}))

        self.assertEqual(_lock_state(assignment)[:2], (None, PENDING))
        save_at = events.index(("save", DoorCodeLockAssignment))
        self.assertIn(("lock", DoorCode), events[:save_at])
