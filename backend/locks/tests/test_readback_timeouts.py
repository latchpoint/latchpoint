"""Issue #199: a readback ``get`` that times out isn't asked again, it waits longer instead."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from integrations_zwavejs.manager import ZwavejsCommandError, ZwavejsCommandTimeout

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.models import Entity
from alarm.tests.settings_test_utils import EncryptionTestMixin
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_lock_push import FakeGateway
from locks.use_cases import lock_config_sync as lock_config_sync_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.lock_push import (
    BudgetedGateway,
    LockCodeUnverified,
    LockUnreachable,
    TimeBudgetExceeded,
    push_door_code_to_lock,
)

PIN = "4321"
NODE = 12
LOCK = "lock.back_door"
EMPTY = {"userIdStatus": 0, "userCode": ""}
UNKNOWN = {"userIdStatus": 254, "userCode": ""}
HOLDS_PIN = {"userIdStatus": 1, "userCode": PIN}


def _timeout() -> ZwavejsCommandTimeout:
    return ZwavejsCommandTimeout("Z-Wave JS command timed out after 15.0s")


class _Clock:
    """Stands in for ``lock_push._time``, so the deadline and the budget run out without real waiting."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _ClockedGateway(FakeGateway):
    """A FakeGateway whose CC 99 ``get``s take time on ``clock``.

    The nth ``get`` takes ``get_seconds[n]`` (none once they run out), and one
    scripted to raise :class:`ZwavejsCommandTimeout` takes its whole timeout,
    like a wait that ran out.
    """

    def __init__(self, *, clock: _Clock, get_seconds: list[float] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.clock = clock
        self.get_seconds = list(get_seconds or [])
        self.get_timeouts: list[float] = []

    def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
        if command_class == 99 and method_name == "get":
            self.get_timeouts.append(timeout_seconds)
            script = self._get_scripts.get(node_id) or self._get_scripts.get(None)
            takes = self.get_seconds.pop(0) if self.get_seconds else 0.0
            self.clock.now += timeout_seconds if script and isinstance(script[0], ZwavejsCommandTimeout) else takes
        return super().invoke_cc_api(
            node_id=node_id,
            command_class=command_class,
            method_name=method_name,
            args=args,
            timeout_seconds=timeout_seconds,
        )


class _ClockTestMixin:
    def setUp(self):
        super().setUp()
        self.clock = _Clock()
        patcher = patch.object(lock_push_uc, "_time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _gateway(self, get_responses: list, *, get_seconds: list[float] | None = None) -> _ClockedGateway:
        return _ClockedGateway(
            clock=self.clock,
            get_seconds=get_seconds,
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=get_responses,
        )


class VerifyUserCodeSlotTimeoutTests(_ClockTestMixin, SimpleTestCase):
    def _verify(self, zwavejs) -> bool:
        return lock_push_uc._verify_user_code_slot(zwavejs=zwavejs, node_id=NODE, slot_index=1, pin=PIN)

    def test_a_get_that_times_out_is_not_asked_again(self):
        gateway = self._gateway([_timeout(), HOLDS_PIN])

        with self.assertRaises(LockCodeUnverified) as ctx:
            self._verify(gateway)

        self.assertFalse(ctx.exception.read_back_empty)
        self.assertIn("ZwavejsCommandTimeout", str(ctx.exception))
        self.assertEqual(gateway.get_timeouts, [lock_push_uc._READBACK_GET_TIMEOUT_SECONDS])
        self.assertEqual(self.clock.sleeps, [])

    def test_an_empty_answer_then_a_timeout_keeps_read_back_empty(self):
        gateway = self._gateway([EMPTY, _timeout()])

        with self.assertRaises(LockCodeUnverified) as ctx:
            self._verify(gateway)

        self.assertTrue(ctx.exception.read_back_empty)
        self.assertEqual(len(gateway.get_timeouts), 2)

    def test_answers_with_no_verdict_still_get_3_asks(self):
        gateway = self._gateway([UNKNOWN, None, HOLDS_PIN])

        self.assertTrue(self._verify(gateway))

        self.assertEqual(len(gateway.get_timeouts), 3)
        self.assertEqual(self.clock.sleeps, [1.0, 2.0])

    def test_a_fast_command_error_is_asked_again(self):
        gateway = self._gateway([ZwavejsCommandError("Z-Wave error 202: timeout"), HOLDS_PIN])

        self.assertTrue(self._verify(gateway))

        self.assertEqual(len(gateway.get_timeouts), 2)

    def test_fast_command_errors_get_3_asks_before_giving_up(self):
        gateway = self._gateway([ZwavejsCommandError("Z-Wave error 202: timeout") for _ in range(3)])

        with self.assertRaises(LockCodeUnverified) as ctx:
            self._verify(gateway)

        self.assertFalse(ctx.exception.read_back_empty)
        self.assertEqual(len(gateway.get_timeouts), 3)

    def test_a_reask_whose_delay_does_not_fit_before_the_deadline_is_skipped(self):
        # The answer took 17.5s, so 0.5s of the 18s is left for a 1s delay.
        gateway = self._gateway([UNKNOWN, HOLDS_PIN], get_seconds=[17.5])

        with self.assertRaises(LockCodeUnverified):
            self._verify(gateway)

        self.assertEqual(len(gateway.get_timeouts), 1)
        self.assertEqual(self.clock.sleeps, [])

    def test_each_get_waits_for_what_is_left_of_the_deadline_and_the_last_delay_must_fit(self):
        # 10s answer, 1s delay, then the second get gets the 7s left and answers
        # in 5.5s, so 1.5s is left for the 2s delay.
        gateway = self._gateway([UNKNOWN, EMPTY, HOLDS_PIN], get_seconds=[10.0, 5.5])

        with self.assertRaises(LockCodeUnverified) as ctx:
            self._verify(gateway)

        self.assertTrue(ctx.exception.read_back_empty)
        self.assertEqual(gateway.get_timeouts, [15.0, 7.0])
        self.assertEqual(self.clock.sleeps, [1.0])

    def test_a_timeout_that_runs_out_the_budget_is_out_of_time(self):
        gateway = self._gateway([_timeout(), HOLDS_PIN])
        budgeted = BudgetedGateway(gateway, seconds=10.0)

        with self.assertRaises(TimeBudgetExceeded):
            self._verify(budgeted)

        # The budget cut the wait short and nothing was asked again.
        self.assertEqual(gateway.get_timeouts, [10.0])
        self.assertTrue(budgeted.exhausted)
        self.assertEqual(self.clock.sleeps, [])

    def test_a_timeout_that_runs_out_the_budget_after_an_empty_answer_keeps_read_back_empty(self):
        gateway = self._gateway([EMPTY, _timeout()])
        budgeted = BudgetedGateway(gateway, seconds=10.0)

        with self.assertRaises(LockCodeUnverified) as ctx:
            self._verify(budgeted)

        self.assertTrue(ctx.exception.read_back_empty)
        self.assertEqual(len(gateway.get_timeouts), 2)

    def test_lock_sync_tracked_slot_readback_stops_at_a_timeout(self):
        gateway = self._gateway([_timeout(), EMPTY, EMPTY])

        self.assertFalse(
            lock_config_sync_uc._tracked_slot_reads_back_empty(zwavejs=gateway, node_id=NODE, slot_index=1)
        )

        self.assertEqual(len(gateway.get_timeouts), 1)


class PostSetReadbackTimeoutTests(_ClockTestMixin, EncryptionTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=LOCK,
            domain="lock",
            name="Back Door",
            attributes={"zwavejs": {"node_id": NODE}},
            source="home_assistant",
        )
        self.code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(PIN),
            pin_length=len(PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=self.code, lock_entity_id=LOCK)

    def _push(self, zwavejs) -> None:
        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=self.code, lock_entity_id=LOCK, zwavejs=zwavejs)

    def _gets(self, gateway: FakeGateway) -> int:
        return sum(1 for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "get")

    def _marker(self, action: str) -> dict | None:
        event = DoorCodeEvent.objects.filter(door_code=self.code, metadata__action=action).order_by("-id").first()
        return event.metadata if event else None

    def test_a_readback_timeout_sends_one_get_and_counts_the_attempt(self):
        gateway = self._gateway([_timeout(), _timeout(), _timeout()])

        self._push(gateway)

        self.assertEqual(self._gets(gateway), 1)
        assignment = DoorCodeLockAssignment.objects.get(door_code=self.code)
        self.assertEqual(
            (assignment.slot_index, assignment.push_state, assignment.push_attempt_count),
            (None, DoorCode.PushState.PENDING, 1),
        )
        self.assertIn("LockCodeUnverified", assignment.last_push_error)
        self.assertIn("ZwavejsCommandTimeout", assignment.last_push_error)
        # The set went into an Available slot nothing saw empty, so #193's tag still goes on.
        marker = self._marker(lock_push_uc._UNCONFIRMED_PUSH_ACTION)
        self.assertEqual((marker["slot_index"], marker.get("slot_available")), (1, True))
        self.assertIsNone(self._marker(lock_push_uc._SLOT_SEEN_EMPTY_ACTION))

    def test_an_empty_answer_then_a_timeout_leaves_the_empty_marker_and_no_tag(self):
        gateway = self._gateway([EMPTY, _timeout(), _timeout()])

        self._push(gateway)

        self.assertEqual(self._gets(gateway), 2)
        self.assertEqual(self._marker(lock_push_uc._SLOT_SEEN_EMPTY_ACTION)["slot_index"], 1)
        marker = self._marker(lock_push_uc._UNCONFIRMED_PUSH_ACTION)
        self.assertEqual(marker["slot_index"], 1)
        self.assertNotIn("slot_available", marker)

    def test_a_readback_timeout_that_runs_out_the_budget_is_not_counted(self):
        gateway = self._gateway([_timeout(), _timeout(), _timeout()])

        self._push(BudgetedGateway(gateway, seconds=10.0))

        self.assertEqual(self._gets(gateway), 1)
        assignment = DoorCodeLockAssignment.objects.get(door_code=self.code)
        self.assertEqual((assignment.push_state, assignment.push_attempt_count), (DoorCode.PushState.PENDING, 0))
        self.assertIn("TimeBudgetExceeded", assignment.last_push_error)
        # The set went out, so the slot is still on record.
        self.assertEqual(self._marker(lock_push_uc._UNCONFIRMED_PUSH_ACTION)["slot_index"], 1)
