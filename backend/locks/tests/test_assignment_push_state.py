"""Issues #126 and #123: per-lock push state on DoorCodeLockAssignment (migrations 0009/0010 and the dual writes)."""

from __future__ import annotations

import importlib
from datetime import timedelta
from unittest.mock import patch

from django.apps import apps as django_apps
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from integrations_zwavejs.manager import ZwavejsCommandError, ZwavejsNotConfigured
from rest_framework.test import APITestCase

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.models import Entity
from alarm.tests.settings_test_utils import EncryptionTestMixin
from locks.models import DoorCode, DoorCodeLockAssignment
from locks.tests import test_lock_config_sync_api as sync_tests
from locks.tests.test_lock_push import ClearFailingGateway, FakeGateway, _TwoLockUpdateTestBase
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.lock_push import LockPushFailed, LockSlotsFull, LockUnreachable, push_door_code_to_lock

PENDING = DoorCode.PushState.PENDING
PUSHED = DoorCode.PushState.PUSHED
FAILED = DoorCode.PushState.FAILED


def _lock_state(assignment: DoorCodeLockAssignment) -> tuple:
    assignment.refresh_from_db()
    return (
        assignment.slot_index,
        assignment.push_state,
        assignment.push_attempt_count,
        assignment.last_push_error,
        assignment.schedule_pending,
    )


class BackfillAssignmentPushStateTests(TestCase):
    """Migration 0010: one case per backfill rule, and the code's own state is left alone."""

    LOCK = "lock.front_door"
    OTHER_LOCK = "lock.back_door"

    @property
    def migration(self):
        return importlib.import_module("locks.migrations.0010_backfill_assignment_push_state")

    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", password="pass")
        self.attempted_at = timezone.now() - timedelta(hours=1)

    def _code(self, *, push_state: str, is_active: bool = True) -> DoorCode:
        return DoorCode.objects.create(
            user=self.user,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=is_active,
            push_state=push_state,
            push_attempt_count=7,
            last_push_attempt_at=self.attempted_at,
            last_push_error="Lock rejected the code",
        )

    def _assignment(self, code: DoorCode, *, slot_index: int | None, lock: str = LOCK) -> DoorCodeLockAssignment:
        # Whatever the columns held before, the backfill decides them.
        return DoorCodeLockAssignment.objects.create(
            door_code=code,
            lock_entity_id=lock,
            slot_index=slot_index,
            push_state=FAILED if slot_index is not None else PUSHED,
            push_attempt_count=99,
            last_push_error="stale",
            schedule_pending=True,
        )

    def _run(self) -> None:
        self.migration._backfill_assignment_push_state(django_apps, None)

    def _row(self, assignment: DoorCodeLockAssignment) -> tuple:
        assignment.refresh_from_db()
        return (
            assignment.push_state,
            assignment.push_attempt_count,
            assignment.last_push_attempt_at,
            assignment.last_push_error,
            assignment.schedule_pending,
        )

    def test_assignment_with_a_slot_is_pushed(self):
        for push_state in (PUSHED, PENDING, FAILED):
            with self.subTest(push_state=push_state):
                assignment = self._assignment(
                    self._code(push_state=push_state), slot_index=1, lock=f"lock.{push_state}"
                )

                self._run()

                self.assertEqual(self._row(assignment), (PUSHED, 0, None, "", False))

    def test_assignment_without_a_slot_on_an_active_failed_code_copies_the_failure(self):
        code = self._code(push_state=FAILED)
        no_slot = self._assignment(code, slot_index=None)
        with_slot = self._assignment(code, slot_index=2, lock=self.OTHER_LOCK)

        self._run()

        self.assertEqual(self._row(no_slot), (FAILED, 7, self.attempted_at, "Lock rejected the code", False))
        self.assertEqual(self._row(with_slot), (PUSHED, 0, None, "", False))

    def test_assignment_without_a_slot_otherwise_is_pending_with_the_codes_attempts(self):
        cases = {
            "active pending": self._code(push_state=PENDING),
            "active pushed": self._code(push_state=PUSHED),
            "inactive failed": self._code(push_state=FAILED, is_active=False),
            "inactive pending": self._code(push_state=PENDING, is_active=False),
        }
        assignments = {name: self._assignment(code, slot_index=None) for name, code in cases.items()}

        self._run()

        for name, assignment in assignments.items():
            with self.subTest(name):
                self.assertEqual(self._row(assignment), (PENDING, 7, self.attempted_at, "", False))

    def test_door_code_push_state_is_untouched(self):
        codes = [
            self._code(push_state=PENDING),
            self._code(push_state=PUSHED),
            self._code(push_state=FAILED),
            self._code(push_state=FAILED, is_active=False),
        ]
        for index, code in enumerate(codes):
            self._assignment(code, slot_index=None)
            self._assignment(code, slot_index=index + 1, lock=self.OTHER_LOCK)
        fields = ("id", "push_state", "push_attempt_count", "last_push_attempt_at", "last_push_error", "updated_at")
        before = list(DoorCode.objects.order_by("id").values_list(*fields))

        self._run()

        self.assertEqual(list(DoorCode.objects.order_by("id").values_list(*fields)), before)

    def test_reverse_is_a_no_op(self):
        [operation] = self.migration.Migration.operations
        self.assertIs(operation.reverse_code, operation.noop)


class AssignmentDbDefaultTests(TestCase):
    """Migration 0009: code from before it can still insert assignments after a rollback."""

    def test_insert_without_the_new_columns_gets_the_db_defaults(self):
        user = User.objects.create_user(email="u@example.com", password="pass")
        code = DoorCode.objects.create(user=user, code_type=DoorCode.CodeType.PERMANENT)
        now = connection.ops.adapt_datetimefield_value(timezone.now())
        qn = connection.ops.quote_name
        columns = ", ".join(qn(c) for c in ("door_code_id", "lock_entity_id", "slot_index", "created_at", "updated_at"))

        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {qn(DoorCodeLockAssignment._meta.db_table)} ({columns}) VALUES (%s, %s, %s, %s, %s)",
                [code.id, "lock.front_door", None, now, now],
            )

        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual(
            (
                assignment.push_state,
                assignment.push_attempt_count,
                assignment.last_push_attempt_at,
                assignment.last_push_error,
                assignment.schedule_pending,
            ),
            (PENDING, 0, None, "", False),
        )


class PushDualWriteTests(_TwoLockUpdateTestBase):
    """The push writes each lock's outcome to its assignment next to the code-level fields."""

    def _code_on_back(self, **assignment_fields) -> tuple[DoorCode, DoorCodeLockAssignment]:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        assignment = DoorCodeLockAssignment.objects.create(
            door_code=code, lock_entity_id=self.BACK, **assignment_fields
        )
        return code, assignment

    def _push(self, code: DoorCode, gateway: FakeGateway) -> None:
        push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

    def test_success_marks_the_lock_pushed_and_resets_it(self):
        code, assignment = self._code_on_back(push_attempt_count=3, last_push_error="old")

        self._push(code, FakeGateway(usersNumber=5, cache_updates_on_set=True))

        self.assertEqual(_lock_state(assignment), (1, PUSHED, 0, "", False))
        code.refresh_from_db()
        self.assertEqual(assignment.last_push_attempt_at, code.last_push_attempt_at)

    def test_transient_failure_keeps_the_lock_pending_and_counts_it(self):
        code, assignment = self._code_on_back(push_attempt_count=2)
        gateway = FakeGateway(usersNumber=5, invoke_raises=ZwavejsCommandError("driver TimeoutError after 5.0s"))

        # The set times out, then the retry's readback of that slot times out too.
        for expected_count in (3, 4):
            with self.assertRaises(LockUnreachable):
                self._push(code, gateway)
            slot_index, state, count, error, schedule_pending = _lock_state(assignment)
            self.assertEqual((slot_index, state, count, schedule_pending), (None, PENDING, expected_count, False))
            self.assertIn("ZwavejsCommandError", error)
            code.refresh_from_db()
            self.assertEqual(assignment.last_push_attempt_at, code.last_push_attempt_at)

    def test_terminal_failure_marks_the_lock_failed(self):
        code, assignment = self._code_on_back(push_attempt_count=2)
        gateway = FakeGateway(usersNumber=5, invoke_raises=ZwavejsNotConfigured("ws_url not set"))

        with self.assertRaises(LockPushFailed):
            self._push(code, gateway)

        # A terminal failure counts an attempt on the lock now, since the code's
        # count only counts clear retries (issue #126) and PR #192 counts the attempt.
        self.assertEqual(_lock_state(assignment), (None, FAILED, 3, "ws_url not set", False))
        code.refresh_from_db()
        self.assertEqual(assignment.last_push_attempt_at, code.last_push_attempt_at)

    def test_slots_full_is_recorded_as_transient(self):
        code, assignment = self._code_on_back()
        gateway = FakeGateway(usersNumber=2, slot_status={1: 1, 2: 1})

        with self.assertRaises(LockSlotsFull):
            self._push(code, gateway)

        slot_index, state, count, error, _ = _lock_state(assignment)
        self.assertEqual((slot_index, state, count), (None, PENDING, 1))
        self.assertIn("Available", error)
        self.assertIsNotNone(assignment.last_push_attempt_at)

    def test_one_locks_failure_is_only_written_to_that_lock(self):
        gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True, reject_pins={13: {self.PIN}})

        code = door_codes_uc.create_door_code(
            user=self.user, raw_code=self.PIN, lock_entity_ids=[self.BACK, self.SIDE], zwavejs=gateway
        )

        back = DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.BACK)
        side = DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.SIDE)
        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))
        self.assertEqual(_lock_state(side)[:2], (None, FAILED))
        self.assertTrue(side.last_push_error)

    def test_slot_recorded_for_another_code_marks_the_lock_failed(self):
        # #190's IntegrityError path, with the code row now written before the slot.
        _other, other_assignment = self._code_on_back()
        code, assignment = self._code_on_back_for_a_second_code(push_attempt_count=2, last_push_error="old")
        DoorCode.objects.filter(id=code.id).update(push_attempt_count=3)
        code.refresh_from_db()

        class ConcurrentWriterGateway(FakeGateway):
            def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
                if command_class == 99 and method_name == "set":
                    DoorCodeLockAssignment.objects.filter(id=other_assignment.id).update(slot_index=args[0])
                return super().invoke_cc_api(
                    node_id=node_id,
                    command_class=command_class,
                    method_name=method_name,
                    args=args,
                    timeout_seconds=timeout_seconds,
                )

        with self.assertRaises(LockPushFailed):
            self._push(code, ConcurrentWriterGateway(usersNumber=5, cache_updates_on_set=True))

        slot_index, state, count, error, _ = _lock_state(assignment)
        # The rolled back success didn't zero the count the failure adds to.
        self.assertEqual((slot_index, state, count), (None, FAILED, 3))
        self.assertIn("recorded for another door code", error)
        code.refresh_from_db()
        # The rollup, and nothing left to clear zeroes the code's clear-retry count (issue #126).
        self.assertEqual((code.push_state, code.push_attempt_count), (FAILED, 0))
        self.assertEqual(_lock_state(other_assignment), (1, PENDING, 0, "", False))

    def _code_on_back_for_a_second_code(self, **assignment_fields) -> tuple[DoorCode, DoorCodeLockAssignment]:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("8642"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        assignment = DoorCodeLockAssignment.objects.create(
            door_code=code, lock_entity_id=self.BACK, **assignment_fields
        )
        return code, assignment

    def test_rolled_back_success_leaves_the_lock_untouched(self):
        # #190's rollback case, dying at either end of the success block: the
        # slot write, or the code's rollup after it (issue #126).
        from django.db.models.query import QuerySet

        real_update = QuerySet.update

        def dying_refresh(**kwargs):
            raise KeyboardInterrupt

        def dying_update(queryset, **kwargs):
            if queryset.model is DoorCodeLockAssignment and kwargs.get("slot_index") is not None:
                raise KeyboardInterrupt
            return real_update(queryset, **kwargs)

        for target, replacement in (
            (lock_push_uc, ("refresh_push_state", dying_refresh)),
            (QuerySet, ("update", dying_update)),
        ):
            with self.subTest(dies_in=replacement[0]):
                code, assignment = self._code_on_back_for_a_second_code(push_attempt_count=2, last_push_error="old")
                gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)

                with patch.object(target, *replacement), self.assertRaises(KeyboardInterrupt):
                    self._push(code, gateway)

                # It died after the PIN landed, so it's the success block that rolled back.
                self.assertEqual(gateway._lock_codes, {(12, 1): "8642"})
                self.assertEqual(_lock_state(assignment), (None, PENDING, 2, "old", False))
                self.assertIsNone(assignment.last_push_attempt_at)
                code.refresh_from_db()
                self.assertEqual(code.push_state, PENDING)
                DoorCode.objects.filter(id=code.id).delete()

    def test_node_lookup_failure_marks_a_lock_without_a_slot_failed(self):
        Entity.objects.filter(entity_id=self.BACK).update(attributes={})
        code, assignment = self._code_on_back()

        with self.assertRaises(LockPushFailed):
            self._push(code, FakeGateway(usersNumber=5))

        slot_index, state, _, error, _ = _lock_state(assignment)
        self.assertEqual((slot_index, state), (None, FAILED))
        self.assertIn("Z-Wave JS node", error)

    def test_node_lookup_failure_leaves_a_lock_holding_a_slot_pushed(self):
        # PR #195 review: the lookup records its failure before the slot-already-set check.
        Entity.objects.filter(entity_id=self.BACK).update(attributes={})
        code, assignment = self._code_on_back(slot_index=3, push_state=PUSHED)

        with self.assertRaises(LockPushFailed):
            self._push(code, FakeGateway(usersNumber=5))

        self.assertEqual(_lock_state(assignment), (3, PUSHED, 0, "", False))
        self.assertIsNone(assignment.last_push_attempt_at)
        code.refresh_from_db()
        # The code is the rollup of its locks now, and this one holds its slot (issue #126).
        self.assertEqual(code.push_state, PUSHED)


class SlotForgetDualWriteTests(_TwoLockUpdateTestBase):
    """A lock whose slot is let go needs a push there again."""

    def test_forget_cleared_slot_makes_the_lock_pending_and_keeps_its_count(self):
        code, _ = self._pushed_code([self.BACK])
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        DoorCodeLockAssignment.objects.filter(id=assignment.id).update(push_attempt_count=4, schedule_pending=True)

        lock_push_uc.forget_cleared_slot(door_code=code, lock_entity_id=self.BACK, slot_index=1, outcome="cleared")

        self.assertEqual(_lock_state(assignment), (None, PENDING, 4, "", False))

    def test_deactivating_makes_every_lock_pending(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])

        def states():
            return set(DoorCodeLockAssignment.objects.filter(door_code=code).values_list("slot_index", "push_state"))

        self.assertEqual(states(), {(1, PUSHED)})

        self._update(code, gateway, {"is_active": False})

        self.assertEqual(states(), {(None, PENDING)})


class UpdateResetDualWriteTests(_TwoLockUpdateTestBase):
    """A push-relevant change resets the locks it's about to push again."""

    def _change_pin_without_pushing(self, code: DoorCode, gateway: FakeGateway) -> None:
        with patch.object(door_codes_uc, "_push_to_assigned_locks_best_effort"):
            self._update(code, gateway, {"code": "5555"})

    def test_pin_change_resets_each_kept_lock(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        back = DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.BACK)
        side = DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.SIDE)
        DoorCodeLockAssignment.objects.filter(id=back.id).update(push_attempt_count=3)
        DoorCodeLockAssignment.objects.filter(id=side.id).update(
            slot_index=None, push_state=FAILED, push_attempt_count=5, last_push_error="rejected"
        )

        self._change_pin_without_pushing(code, gateway)

        self.assertEqual(_lock_state(back), (None, PENDING, 0, "", False))
        self.assertEqual(_lock_state(side), (None, PENDING, 0, "", False))

    def test_lock_whose_clear_failed_keeps_its_slot_and_state(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {12}

        self._change_pin_without_pushing(code, gateway)

        back = DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.BACK)
        side = DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.SIDE)
        self.assertEqual(_lock_state(back), (1, PUSHED, 0, "", False))
        self.assertEqual(_lock_state(side), (None, PENDING, 0, "", False))

    def test_pin_change_then_push_marks_each_lock_pushed(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])

        self._update(code, gateway, {"code": "5555"})

        for assignment in DoorCodeLockAssignment.objects.filter(door_code=code):
            self.assertEqual(_lock_state(assignment), (1, PUSHED, 0, "", False))


class RetryDualWriteTests(_TwoLockUpdateTestBase):
    """Retry re-arms each failed lock before pushing it."""

    def test_retry_resets_a_failed_lock_before_the_push(self):
        rejecting = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True, admin_code=self.PIN)
        code = door_codes_uc.create_door_code(
            user=self.user, raw_code=self.PIN, lock_entity_ids=[self.BACK], zwavejs=rejecting
        )
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual(_lock_state(assignment)[:2], (None, FAILED))
        DoorCodeLockAssignment.objects.filter(id=assignment.id).update(push_attempt_count=5)
        timing_out = FakeGateway(usersNumber=5, invoke_raises=ZwavejsCommandError("driver TimeoutError after 5.0s"))

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=timing_out)

        slot_index, state, count, error, _ = _lock_state(assignment)
        # Reset to 0 first, then this push's timeout counts once.
        self.assertEqual((slot_index, state, count), (None, PENDING, 1))
        self.assertIn("ZwavejsCommandError", error)

    def test_retry_resets_a_failed_lock_on_a_code_that_isnt_failed(self):
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            push_state=PENDING,
            push_attempt_count=3,
        )
        assignment = DoorCodeLockAssignment.objects.create(
            door_code=code, lock_entity_id=self.BACK, push_state=FAILED, push_attempt_count=5, last_push_error="x"
        )
        timing_out = FakeGateway(usersNumber=5, invoke_raises=ZwavejsCommandError("driver TimeoutError after 5.0s"))

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=timing_out)

        slot_index, state, count, error, _ = _lock_state(assignment)
        self.assertEqual((slot_index, state, count), (None, PENDING, 1))
        self.assertIn("ZwavejsCommandError", error)
        code.refresh_from_db()
        # Retry always resets the code's clear-retry count now, and the timeout counts on the lock (issue #126).
        self.assertEqual((code.push_state, code.push_attempt_count), (PENDING, 0))

    def test_retry_pushes_a_failed_lock(self):
        rejecting = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True, admin_code=self.PIN)
        code = door_codes_uc.create_door_code(
            user=self.user, raw_code=self.PIN, lock_entity_ids=[self.BACK], zwavejs=rejecting
        )

        door_codes_uc.retry_push_door_code(
            code=code, actor_user=self.user, zwavejs=FakeGateway(usersNumber=5, cache_updates_on_set=True)
        )

        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual(_lock_state(assignment), (1, PUSHED, 0, "", False))


class SchedulerCapDualWriteTests(_TwoLockUpdateTestBase):
    """The scheduler's cap fails each lock still waiting on a push along with the code."""

    def test_cap_fails_the_locks_still_waiting_and_keeps_their_own_error(self):
        # Each lock's own count against the cap now (issue #126), not the code's.
        from locks.tasks import push_pending_door_codes

        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            push_state=PENDING,
        )
        waiting = DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK, push_attempt_count=23)
        on_lock = DoorCodeLockAssignment.objects.create(
            door_code=code, lock_entity_id=self.SIDE, slot_index=2, push_state=PUSHED
        )
        gateway = FakeGateway(usersNumber=5, invoke_raises=ZwavejsCommandError("driver TimeoutError after 5.0s"))

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()

        code.refresh_from_db()
        self.assertEqual(code.push_state, FAILED)
        self.assertIn(f"{self.BACK}: Push gave up after 24 attempts", code.last_push_error)
        slot_index, state, count, error, _ = _lock_state(waiting)
        self.assertEqual((slot_index, state, count), (None, FAILED, 24))
        self.assertIn("ZwavejsCommandError", error)
        self.assertNotIn("gave up", error)
        self.assertEqual(_lock_state(on_lock), (2, PUSHED, 0, "", False))

    def _cap_on_clear_retries_after(self, changes: dict) -> tuple[DoorCode, DoorCodeLockAssignment]:
        """Back's clear keeps failing after ``changes``, and the clear retries take the code to the cap.

        Side's clear works, so it ends up ``pending`` with no slot.
        """
        from locks.tasks import push_pending_door_codes

        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {12}
        code = self._update(code, gateway, changes)
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: None})
        side = DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.SIDE)
        self.assertEqual(_lock_state(side)[:2], (None, PENDING))
        DoorCode.objects.filter(id=code.id).update(push_attempt_count=23)

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()

        code.refresh_from_db()
        self.assertEqual(code.push_state, FAILED)
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: None})
        return code, side

    def test_cap_leaves_the_locks_of_a_code_that_hasnt_started_pending(self):
        # PR #195 review: its start moved 2h ahead, so the cap only counted clear
        # retries, and enforce_door_code_validity pushes Side once it starts.
        _code, side = self._cap_on_clear_retries_after({"start_at": timezone.now() + timedelta(hours=2)})

        self.assertEqual(_lock_state(side)[:2], (None, PENDING))

    def test_cap_leaves_the_locks_of_an_inactive_code_pending(self):
        _code, side = self._cap_on_clear_retries_after({"is_active": False})

        self.assertEqual(_lock_state(side)[:2], (None, PENDING))


class LockSyncDualWriteTests(EncryptionTestMixin, APITestCase):
    """Lock config sync keeps each lock's state in step with the slots it records or lets go."""

    LOCK = sync_tests.LockConfigSyncReconcileTests.LOCK
    setUp = sync_tests.LockConfigSyncReconcileTests.setUp
    _sync = sync_tests.LockConfigSyncReconcileTests._sync
    _manual_code = sync_tests.LockConfigSyncReconcileTests._manual_code

    def test_imported_slot_is_pushed(self):
        self._sync(sync_tests.SlotGateway({1: (1, "1234")}))

        assignment = DoorCodeLockAssignment.objects.get(lock_entity_id=self.LOCK)
        self.assertEqual(_lock_state(assignment), (1, PUSHED, 0, "", False))

    def test_released_slot_is_pending_and_keeps_its_count(self):
        self._sync(sync_tests.SlotGateway({1: (1, "1234")}))
        assignment = DoorCodeLockAssignment.objects.get(lock_entity_id=self.LOCK)
        DoorCodeLockAssignment.objects.filter(id=assignment.id).update(push_attempt_count=2)
        self.assertEqual(_lock_state(assignment)[:2], (1, PUSHED))

        self._sync(sync_tests.SlotGateway({1: (0, None)}))

        self.assertEqual(_lock_state(assignment), (None, PENDING, 2, "", False))

    def test_manual_code_converted_to_synced_is_pushed(self):
        code = self._manual_code(pin="4321", slot_index=1)
        DoorCodeLockAssignment.objects.filter(door_code=code).update(
            push_state=PENDING, push_attempt_count=3, last_push_error="old"
        )

        self._sync(sync_tests.SlotGateway({1: (1, "4321")}))

        code.refresh_from_db()
        self.assertEqual(code.source, DoorCode.Source.SYNCED)
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual(_lock_state(assignment), (1, PUSHED, 0, "", False))
