"""How door code push failures are classified and retried (issues #191, #186, #203)."""

from __future__ import annotations

from datetime import time
from unittest.mock import patch

from django.db import OperationalError
from django.db.models.query import QuerySet
from django.test import TestCase
from integrations_zwavejs.manager import ZwavejsClientUnavailable, ZwavejsCommandError

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.models import Entity
from alarm.tests.settings_test_utils import EncryptionTestMixin
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_door_code_lifecycle import _LifecycleTestBase
from locks.tests.test_door_code_locking import BACK, _FakeClock, _free_elsewhere, _LockingTestBase, _OtherHolder
from locks.tests.test_lock_push import FakeGateway
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_config_sync as lock_config_sync_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.lock_push import LockUnreachable, push_door_code_to_lock

LOCK = "lock.front_door"  # node 7


def _unavailable() -> ZwavejsClientUnavailable:
    return ZwavejsClientUnavailable("Z-Wave JS client is unavailable.")


class _ClientDownGateway(FakeGateway):
    """A FakeGateway whose Z-Wave JS client is unavailable while ``down``, from the first call of a push."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.down = True

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0):
        if self.down:
            raise _unavailable()
        return super().node_get_defined_value_ids(node_id=node_id, timeout_seconds=timeout_seconds)


class _ScheduleClientDownGateway(FakeGateway):
    """A FakeGateway whose CC 78 schedule calls find the client unavailable while ``down``."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.down = True

    def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
        if command_class == 78 and self.down:
            raise _unavailable()
        return super().invoke_cc_api(
            node_id=node_id,
            command_class=command_class,
            method_name=method_name,
            args=args,
            timeout_seconds=timeout_seconds,
        )


class ClientUnavailableIsTransientTests(EncryptionTestMixin, TestCase):
    """Issue #191: Z-Wave JS down or restarting leaves the lock pending for the scheduler, under its cap."""

    PIN = "1234"

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=LOCK,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )
        patcher = patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_code(self, **kwargs) -> DoorCode:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=kwargs.pop("code_type", DoorCode.CodeType.PERMANENT),
            is_active=True,
            **kwargs,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=LOCK)
        return code

    @staticmethod
    def _assignment(code: DoorCode) -> DoorCodeLockAssignment:
        return DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=LOCK)

    @staticmethod
    def _markers(code: DoorCode, action: str = "push_unconfirmed") -> list[dict]:
        return list(
            DoorCodeEvent.objects.filter(door_code=code, metadata__action=action).values_list("metadata", flat=True)
        )

    @staticmethod
    def _cc(gateway: FakeGateway, command_class: int, method_name: str) -> list[list]:
        return [
            c["args"]
            for c in gateway.invoke_calls
            if c["command_class"] == command_class and c["method_name"] == method_name
        ]

    def _push(self, code: DoorCode, gateway: FakeGateway):
        return push_door_code_to_lock(door_code=code, lock_entity_id=LOCK, zwavejs=gateway)

    def _push_pending(self, gateway: FakeGateway) -> int:
        from locks.tasks import push_pending_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            return push_pending_door_codes()

    def _assert_pending_and_counted(self, code: DoorCode, *, attempts: int = 1) -> DoorCodeLockAssignment:
        assignment = self._assignment(code)
        self.assertEqual((assignment.push_state, assignment.push_attempt_count), (DoorCode.PushState.PENDING, attempts))
        self.assertIn("ZwavejsClientUnavailable", assignment.last_push_error)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        # Not a terminal failure, so no code_failed event for the push.
        self.assertFalse(DoorCodeEvent.objects.filter(door_code=code, metadata__action="push").exists())
        return assignment

    def test_client_unavailable_leaves_the_lock_pending_and_the_scheduler_pushes_it_once_back(self):
        gateway = _ClientDownGateway(usersNumber=3)
        code = self._make_code()

        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)

        self._assert_pending_and_counted(code)
        self.assertEqual(self._cc(gateway, 99, "set"), [])

        gateway.down = False
        self.assertEqual(self._push_pending(gateway), 1)

        assignment = self._assignment(code)
        self.assertEqual((assignment.slot_index, assignment.push_state), (1, DoorCode.PushState.PUSHED))
        self.assertEqual(gateway._lock_codes, {(7, 1): self.PIN})

    def test_client_unavailable_counts_toward_the_cap_and_fails_the_lock_there(self):
        gateway = _ClientDownGateway(usersNumber=3)
        code = self._make_code()

        with patch("locks.tasks._get_push_max_attempts", return_value=2):
            self._push_pending(gateway)
            # Retried by the next tick, not failed for good (issue #191).
            self._assert_pending_and_counted(code)
            self._push_pending(gateway)

        assignment = self._assignment(code)
        self.assertEqual((assignment.push_state, assignment.push_attempt_count), (DoorCode.PushState.FAILED, 2))
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)

    def test_client_unavailable_from_the_set_itself_leaves_no_marker(self):
        # Nothing went out, like the budget refusing the set, and like PR #192's terminal case did.
        gateway = FakeGateway(usersNumber=3, invoke_raises=_unavailable(), invoke_raises_after=0)
        code = self._make_code()

        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)

        self.assertEqual(self._cc(gateway, 99, "set"), [[1, 1, self.PIN]])
        self.assertEqual(self._markers(code), [])
        self._assert_pending_and_counted(code)

    def test_client_unavailable_during_the_readback_keeps_the_slot_on_record_for_a_delete(self):
        # The set returned, so the PIN may be in the slot: a marker like PR #192's
        # terminal case left, now a timeout-like one since the readback saw no empty answer.
        gateway = FakeGateway(usersNumber=3, get_responses=[_unavailable() for _ in range(3)])
        code = self._make_code()

        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)

        [marker] = self._markers(code)
        self.assertEqual(marker["slot_index"], 1)
        self.assertTrue(marker.get("slot_available"))
        self.assertNotIn("slot_verified", marker)
        self.assertIsNone(self._assignment(code).slot_index)
        self._assert_pending_and_counted(code)

        gateway.invoke_calls.clear()
        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._cc(gateway, 99, "get"), [[1]])
        self.assertEqual(self._cc(gateway, 99, "clear"), [[1]])
        self.assertEqual(gateway._lock_codes, {})

    def test_an_empty_answer_before_the_client_went_away_still_drops_the_masked_trust(self):
        # PR #193: a readback that answered empty once leaves its marker and the attempt isn't slot_available.
        gateway = FakeGateway(
            usersNumber=3,
            get_responses=[{"userIdStatus": 0, "userCode": ""}, _unavailable(), _unavailable()],
        )
        code = self._make_code()

        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)

        [marker] = self._markers(code)
        self.assertEqual(marker["slot_index"], 1)
        self.assertNotIn("slot_available", marker)
        self.assertNotIn("slot_verified", marker)
        self.assertEqual([m["slot_index"] for m in self._markers(code, "slot_read_back_empty")], [1])
        self._assert_pending_and_counted(code)

    def test_client_unavailable_during_the_schedule_leaves_it_pending_and_only_the_schedule_goes_out_next(self):
        gateway = _ScheduleClientDownGateway(usersNumber=3, cache_updates_on_set=True)
        code = self._make_code(
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b1,
            window_start=time(9, 0),
            window_end=time(17, 0),
        )

        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)

        assignment = self._assert_pending_and_counted(code)
        self.assertEqual((assignment.slot_index, assignment.schedule_pending), (1, True))
        self.assertIn("Schedule not applied", assignment.last_push_error)

        gateway.down = False
        gateway.invoke_calls.clear()
        self._push(code, gateway)

        assignment = self._assignment(code)
        self.assertEqual(
            (assignment.slot_index, assignment.push_state, assignment.schedule_pending),
            (1, DoorCode.PushState.PUSHED, False),
        )
        self.assertEqual(self._cc(gateway, 99, "set"), [])
        self.assertTrue(self._cc(gateway, 78, "setDailyRepeatingSchedule"))


class ValidityTaskDbErrorTests(_LifecycleTestBase):
    """Issue #186: a DB error while loading a pass's codes is logged, never raised."""

    def test_a_db_error_loading_any_pass_is_logged_and_the_task_returns(self):
        gateway = FakeGateway(usersNumber=3)
        real_fetch_all = QuerySet._fetch_all

        for failing_load in (1, 2, 3):
            with self.subTest(failing_load=failing_load):
                loads: list[QuerySet] = []

                def fetch_all(queryset, failing_load=failing_load, loads=loads):
                    if queryset._result_cache is None:
                        loads.append(queryset)
                        if len(loads) >= failing_load:
                            raise OperationalError("server closed the connection unexpectedly")
                    return real_fetch_all(queryset)

                with (
                    patch.object(QuerySet, "_fetch_all", fetch_all),
                    self.assertLogs("locks.tasks", level="WARNING") as logs,
                ):
                    self.assertEqual(self._enforce(gateway), 0)

                self.assertEqual(len(loads), failing_load)
                self.assertIn("Couldn't load door codes to enforce their validity", logs.output[0])


class WithdrawReadsTheSlotBackTests(_LifecycleTestBase):
    """Issue #186: the withdraw of a code pushed before its start reads its tracked slot back like #167's clear."""

    MASKED = {"userIdStatus": 1, "userCode": "****"}

    def _early_pushed_code(self):
        code, gateway = self._temporary_code([self.BACK])
        self._move(code, start_at=self._from_now(hours=1))
        self.assertEqual(self._slots(code), {self.BACK: 1})
        return code, gateway

    def _withdrawn_event(self, code: DoorCode) -> DoorCodeEvent:
        return DoorCodeEvent.objects.filter(door_code=code, metadata__action="withdrawn").get()

    def test_a_keypad_code_typed_into_the_slot_since_is_left_alone(self):
        code, gateway = self._early_pushed_code()
        gateway._lock_codes[(12, 1)] = "9999"

        self.assertEqual(self._enforce(gateway), 1)

        self.assertEqual(self._calls(gateway, "get"), [(12, [1])])
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: "9999"})
        # Not ours any more, so forgotten, and the code goes on a free slot at its start.
        self.assertEqual(self._slots(code), {self.BACK: None})
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(self._withdrawn_event(code).metadata["cleared_slots"], [])
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])

    def test_a_slot_that_reads_back_our_pin_or_masked_is_cleared(self):
        for masked in (False, True):
            with self.subTest(masked=masked):
                code, gateway = self._early_pushed_code()
                if masked:
                    # A tracked slot is ours on a masked readback, the #167 rule.
                    gateway._get_scripts = {None: [self.MASKED] * 3}

                self._enforce(gateway)

                self.assertEqual(self._calls(gateway, "get"), [(12, [1])])
                self.assertEqual(self._calls(gateway, "clear"), [(12, [1])])
                self.assertEqual(self._lock_codes(gateway, 12), {})
                self.assertEqual(self._slots(code), {self.BACK: None})
                self.assertEqual(
                    self._withdrawn_event(code).metadata["cleared_slots"],
                    [{"lock_entity_id": self.BACK, "slot_index": 1}],
                )
                code.delete()

    def test_a_readback_with_no_answer_clears_nothing_and_reads_back_again_next_tick(self):
        code, gateway = self._early_pushed_code()
        gateway._get_scripts = {None: [ZwavejsCommandError("driver TimeoutError after 5.0s") for _ in range(3)]}

        self.assertEqual(self._enforce(gateway), 1)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._slots(code), {self.BACK: 1})
        # Not recorded, so the clear retry doesn't clear it without a readback.
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
        [failure] = self._withdrawn_event(code).metadata["failed_slot_clears"]
        self.assertEqual((failure["lock_entity_id"], failure["slot_index"]), (self.BACK, 1))
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)

        gateway.invoke_calls.clear()
        self._enforce(gateway)

        self.assertEqual(self._calls(gateway, "get"), [(12, [1])])
        self.assertEqual(self._calls(gateway, "clear"), [(12, [1])])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})


class SaveOutwaitsAQueuedPushTests(_LockingTestBase):
    """Issue #203: an update or delete waits longer than a queued push can hold the lock."""

    def setUp(self):
        super().setUp()
        self.clock = _FakeClock()
        self.start = self.clock.now
        for patcher in (
            patch.object(lock_config_sync_uc, "_time", self.clock),
            patch.object(lock_config_sync_uc, "_SYNC_LOCK_POLL_SECONDS", (1.0, 1.0)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _push_holding_back_for_its_whole_budget(self) -> _OtherHolder:
        """The queued push of a just-created code holds BACK for its budget plus a readback sleep past it."""
        push = self._hold_elsewhere(BACK)
        held_for = lock_push_uc.PUSH_LOCK_BUDGET_SECONDS + max(lock_push_uc._READBACK_RETRY_DELAYS_SECONDS) + 1

        def tick(now):
            if now - self.start >= held_for:
                push.release()

        self.clock.on_tick = tick
        return push

    def test_an_edit_right_after_a_create_waits_for_the_queued_push(self):
        code = self._pushed_code([BACK])
        self._push_holding_back_for_its_whole_budget()

        door_codes_uc.update_door_code(
            code=self._fresh(code), changes={"label": "Cleaner"}, actor_user=self.user, zwavejs=self.gateway
        )

        code.refresh_from_db()
        self.assertEqual(code.label, "Cleaner")
        self.assertGreater(self.clock.now - self.start, lock_push_uc.PUSH_LOCK_BUDGET_SECONDS)
        self.assertTrue(_free_elsewhere(BACK))

    def test_a_delete_right_after_a_create_waits_for_the_queued_push(self):
        code = self._pushed_code([BACK])
        self._push_holding_back_for_its_whole_budget()

        door_codes_uc.delete_door_code(code=self._fresh(code), actor_user=self.user, zwavejs=self.gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._lock_codes(12), {})
        self.assertTrue(_free_elsewhere(BACK))
