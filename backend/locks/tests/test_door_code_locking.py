"""Issue #131: door code update, delete and slot clears hold the ``lock_sync:`` lock.

On Postgres the "other holder" is a second database connection holding the
advisory lock, the way a scheduler push in another thread or process would. On
other databases it's the in-process guard's key held by someone else. A waiting
use case is let through by releasing that hold the first time its acquire finds
the lock busy, so nothing here depends on timing.
"""

from __future__ import annotations

import contextlib
from unittest.mock import patch

from django.db import DEFAULT_DB_ALIAS, connection, connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from integrations_zwavejs.manager import ZwavejsCommandError
from rest_framework.test import APITestCase

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.models import Entity
from alarm.tests.settings_test_utils import EncryptionTestMixin
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_lock_config_sync_api import FakeZwavejsGateway, _value_id_key
from locks.tests.test_lock_push import FakeGateway
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_config_sync as lock_config_sync_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.lock_config_sync import LockBusy, hold_lock_sync
from locks.use_cases.lock_push import PushSuperseded, push_door_code_to_assigned_locks, push_door_code_to_lock

BACK = "lock.back_door"  # node 12
SIDE = "lock.side_door"  # node 13
FRONT = "lock.front_door"  # node 14
PIN = "4321"


def _is_postgres() -> bool:
    return connection.vendor == "postgresql"


class _OtherHolder:
    """Holds ``lock_sync:<lock>`` from outside this thread's session."""

    def __init__(self, lock_entity_id: str):
        self.lock_key = f"lock_sync:{lock_entity_id}"
        self._conn = None

    def acquire(self) -> _OtherHolder:
        if _is_postgres():
            self._conn = connections.create_connection(DEFAULT_DB_ALIAS)
            with self._conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s)", [lock_config_sync_uc._pg_lock_id(self.lock_key)])
        else:
            with lock_config_sync_uc._in_flight_lock:
                lock_config_sync_uc._in_flight_keys.add(self.lock_key)
        return self

    def release(self) -> None:
        if self._conn is not None:
            with self._conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_config_sync_uc._pg_lock_id(self.lock_key)])
            self._conn.close()
            self._conn = None
        else:
            with lock_config_sync_uc._in_flight_lock:
                lock_config_sync_uc._in_flight_keys.discard(self.lock_key)


def _free_elsewhere(lock_entity_id: str) -> bool:
    """Whether another session could take ``lock_sync:<lock>`` right now."""
    lock_key = f"lock_sync:{lock_entity_id}"
    if not _is_postgres():
        return lock_key not in lock_config_sync_uc._in_flight_keys
    other = connections.create_connection(DEFAULT_DB_ALIAS)
    try:
        lock_id = lock_config_sync_uc._pg_lock_id(lock_key)
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_id])
            got = bool(cursor.fetchone()[0])
            if got:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])
        return got
    finally:
        other.close()


@contextlib.contextmanager
def _when_waiting_on(lock_entity_id: str, callback):
    """Run ``callback`` the first time a waiting acquire of ``lock_sync:<lock>`` finds it busy."""
    real = lock_config_sync_uc._try_acquire_sync_lock
    fired: list[str] = []

    def wrapper(*, lock_key: str):
        acquired, lock_id = real(lock_key=lock_key)
        if not acquired and lock_key == f"lock_sync:{lock_entity_id}" and not fired:
            fired.append(lock_key)
            callback()
        return acquired, lock_id

    with patch.object(lock_config_sync_uc, "_try_acquire_sync_lock", wrapper):
        yield fired


@contextlib.contextmanager
def _recording_acquires():
    real = lock_config_sync_uc._try_acquire_sync_lock
    keys: list[str] = []

    def wrapper(*, lock_key: str):
        keys.append(lock_key.removeprefix("lock_sync:"))
        return real(lock_key=lock_key)

    with patch.object(lock_config_sync_uc, "_try_acquire_sync_lock", wrapper):
        yield keys


class _LockingTestBase(EncryptionTestMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(email="admin@example.com", password="pass")
        for entity_id, name, node_id in ((BACK, "Back Door", 12), (SIDE, "Side Door", 13), (FRONT, "Front Door", 14)):
            Entity.objects.create(
                entity_id=entity_id,
                domain="lock",
                name=name,
                attributes={"zwavejs": {"node_id": node_id}},
                source="home_assistant",
            )
        self.gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)
        for patcher in (
            patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0)),
            patch.object(lock_config_sync_uc, "_SYNC_LOCK_POLL_SECONDS", (0.01, 0.01)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _hold_elsewhere(self, lock_entity_id: str) -> _OtherHolder:
        holder = _OtherHolder(lock_entity_id).acquire()
        self.addCleanup(holder.release)
        return holder

    def _pending_code(self, lock_entity_ids: list[str], pin: str = PIN) -> DoorCode:
        """An active code assigned to the locks with no slot yet, the way the scheduler finds it."""
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(pin),
            pin_length=len(pin),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        for entity_id in lock_entity_ids:
            DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=entity_id)
        return code

    def _pushed_code(self, lock_entity_ids: list[str]) -> DoorCode:
        code = door_codes_uc.create_door_code(
            user=self.user, raw_code=PIN, lock_entity_ids=lock_entity_ids, actor_user=self.user, zwavejs=self.gateway
        )
        self.gateway.invoke_calls.clear()
        return code

    def _fresh(self, code: DoorCode) -> DoorCode:
        return DoorCode.objects.select_related("user").prefetch_related("lock_assignments").get(id=code.id)

    def _lock_codes(self, node_id: int) -> dict[int, str]:
        return {slot: pin for (node, slot), pin in self.gateway._lock_codes.items() if node == node_id}

    def _slots(self, code: DoorCode) -> dict[str, int | None]:
        return dict(DoorCodeLockAssignment.objects.filter(door_code=code).values_list("lock_entity_id", "slot_index"))

    def _cc99(self, method_name: str) -> list[tuple[int, list]]:
        return [
            (c["node_id"], c["args"])
            for c in self.gateway.invoke_calls
            if c["command_class"] == 99 and c["method_name"] == method_name
        ]


class UpdateAndDeleteWaitForThePushTests(_LockingTestBase):
    """The two races from the #131 comment: a scheduler push of the same code is mid-flight."""

    def _scheduler_push_finishing(self, code: DoorCode, scheduler: _OtherHolder):
        # What the scheduler loaded before the update or delete started.
        stale = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)

        def finish():
            scheduler.release()
            push_door_code_to_lock(door_code=stale, lock_entity_id=BACK, zwavejs=self.gateway)

        return finish

    def test_update_waits_for_the_push_then_moves_its_slot_to_the_new_pin(self):
        code = self._pending_code([BACK])
        scheduler = self._hold_elsewhere(BACK)

        with _when_waiting_on(BACK, self._scheduler_push_finishing(code, scheduler)) as waited:
            door_codes_uc.update_door_code(
                code=self._fresh(code), changes={"code": "5555"}, actor_user=self.user, zwavejs=self.gateway
            )

        self.assertTrue(waited)
        # The push landed the old PIN in slot 1 while the update waited; the update
        # then saw that slot, cleared it and put the new PIN there.
        self.assertEqual(self._cc99("set"), [(12, [1, 1, PIN]), (12, [1, 1, "5555"])])
        self.assertEqual(self._cc99("clear"), [(12, [1])])
        self.assertEqual(self._lock_codes(12), {1: "5555"})
        self.assertEqual(self._slots(code), {BACK: 1})
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertTrue(_free_elsewhere(BACK))

    def test_delete_waits_for_the_push_then_clears_the_slot_it_recorded(self):
        code = self._pending_code([BACK])
        scheduler = self._hold_elsewhere(BACK)

        with _when_waiting_on(BACK, self._scheduler_push_finishing(code, scheduler)) as waited:
            door_codes_uc.delete_door_code(code=self._fresh(code), actor_user=self.user, zwavejs=self.gateway)

        self.assertTrue(waited)
        self.assertEqual(self._cc99("clear"), [(12, [1])])
        self.assertEqual(self._lock_codes(12), {})
        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        deleted = DoorCodeEvent.objects.get(event_type=DoorCodeEvent.EventType.CODE_DELETED)
        self.assertEqual(deleted.metadata["cleared_slots"], [{"lock_entity_id": BACK, "slot_index": 1}])
        self.assertTrue(_free_elsewhere(BACK))

    def test_update_gives_up_after_the_wait_limit_without_changing_anything(self):
        code = self._pushed_code([BACK])
        self._hold_elsewhere(BACK)

        with (
            patch.object(lock_config_sync_uc, "SYNC_LOCK_WAIT_SECONDS", 0.05),
            self.assertRaisesMessage(LockBusy, f"Another operation on {BACK} is still running"),
        ):
            door_codes_uc.update_door_code(
                code=self._fresh(code),
                changes={"code": "5555", "label": "x"},
                actor_user=self.user,
                zwavejs=self.gateway,
            )

        code.refresh_from_db()
        self.assertEqual(code.label, "")
        self.assertEqual(lock_push_uc.decrypt_pin_or_none(code), PIN)
        self.assertEqual(self.gateway.invoke_calls, [])
        self.assertFalse(DoorCodeEvent.objects.filter(event_type=DoorCodeEvent.EventType.CODE_UPDATED).exists())

    def test_delete_gives_up_after_the_wait_limit_and_keeps_the_code(self):
        code = self._pushed_code([BACK, SIDE])
        self._hold_elsewhere(SIDE)

        with (
            patch.object(lock_config_sync_uc, "SYNC_LOCK_WAIT_SECONDS", 0.05),
            self.assertRaises(LockBusy),
        ):
            door_codes_uc.delete_door_code(code=self._fresh(code), actor_user=self.user, zwavejs=self.gateway)

        self.assertEqual(self._slots(code), {BACK: 1, SIDE: 1})
        self.assertEqual(self.gateway.invoke_calls, [])
        # BACK was taken first (sorted) and let go again.
        self.assertTrue(_free_elsewhere(BACK))

    def test_update_of_a_code_deleted_while_it_waited_is_not_found(self):
        code = self._pushed_code([BACK])
        holder = self._hold_elsewhere(BACK)

        def deleted_meanwhile():
            holder.release()
            door_codes_uc.delete_door_code(code=self._fresh(code), actor_user=self.user, zwavejs=self.gateway)

        stale = self._fresh(code)
        with (
            _when_waiting_on(BACK, deleted_meanwhile),
            self.assertRaises(door_codes_uc.NotFound),
        ):
            door_codes_uc.update_door_code(
                code=stale, changes={"lock_entity_ids": [BACK, SIDE]}, actor_user=self.user, zwavejs=self.gateway
            )

        self.assertEqual(self._cc99("set"), [])
        self.assertFalse(DoorCodeLockAssignment.objects.exists())


class StaleSchedulerPushTests(_LockingTestBase):
    """The other order: the scheduler loaded the code, then an update or delete ran before its push got the lock."""

    def test_push_after_an_update_already_pushed_the_lock_doesnt_write_a_second_slot(self):
        code = self._pending_code([BACK])
        stale = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
        door_codes_uc.update_door_code(
            code=self._fresh(code), changes={"code": "5555"}, actor_user=self.user, zwavejs=self.gateway
        )
        self.assertEqual(self._lock_codes(12), {1: "5555"})
        self.gateway.invoke_calls.clear()

        successes, failures = push_door_code_to_assigned_locks(door_code=stale, zwavejs=self.gateway)

        self.assertEqual(failures, [])
        self.assertEqual([s.slot_index for s in successes], [1])
        self.assertEqual(self.gateway.invoke_calls, [])
        self.assertEqual(self._lock_codes(12), {1: "5555"})
        self.assertEqual(self._slots(code), {BACK: 1})

    def test_push_sends_the_pin_saved_while_it_waited(self):
        code = self._pending_code([BACK])
        stale = DoorCode.objects.get(id=code.id)
        DoorCode.objects.filter(id=code.id).update(encrypted_pin=SettingsEncryption.get().encrypt("5555"))

        push_door_code_to_lock(door_code=stale, lock_entity_id=BACK, zwavejs=self.gateway)

        self.assertEqual(self._cc99("set"), [(12, [1, 1, "5555"])])
        self.assertEqual(self._lock_codes(12), {1: "5555"})

    def test_push_of_a_code_turned_off_meanwhile_sends_nothing(self):
        code = self._pending_code([BACK])
        stale = DoorCode.objects.get(id=code.id)
        DoorCode.objects.filter(id=code.id).update(is_active=False)

        with self.assertRaises(PushSuperseded):
            push_door_code_to_lock(door_code=stale, lock_entity_id=BACK, zwavejs=self.gateway)

        self.assertEqual(self.gateway.invoke_calls, [])
        self.assertTrue(_free_elsewhere(BACK))

    def test_push_to_a_lock_dropped_meanwhile_sends_nothing(self):
        code = self._pending_code([BACK, SIDE])
        stale = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=BACK).delete()

        successes, failures = push_door_code_to_assigned_locks(door_code=stale, zwavejs=self.gateway)

        self.assertEqual((successes, failures), ([], []))
        self.assertEqual(self.gateway.invoke_calls, [])

    def test_push_of_a_code_deleted_meanwhile_sends_nothing(self):
        code = self._pending_code([BACK])
        stale = DoorCode.objects.get(id=code.id)
        DoorCode.objects.filter(id=code.id).delete()

        with self.assertRaises(PushSuperseded):
            push_door_code_to_lock(door_code=stale, lock_entity_id=BACK, zwavejs=self.gateway)

        self.assertEqual(self.gateway.invoke_calls, [])


class NestedAcquisitionTests(_LockingTestBase):
    def test_a_push_inside_a_held_lock_stacks_on_it_and_the_outer_hold_stays(self):
        code = self._pending_code([BACK])

        with hold_lock_sync([BACK]):
            # A non re-entrant guard would answer "another sync is in progress" here.
            push_door_code_to_lock(door_code=code, lock_entity_id=BACK, zwavejs=self.gateway)
            self.assertFalse(_free_elsewhere(BACK))

        self.assertTrue(_free_elsewhere(BACK))
        self.assertEqual(self._slots(code), {BACK: 1})

    def test_nested_holds_release_only_their_own_count(self):
        with hold_lock_sync([BACK]):
            with hold_lock_sync([SIDE, BACK]):
                self.assertFalse(_free_elsewhere(SIDE))
            self.assertFalse(_free_elsewhere(BACK))
            self.assertTrue(_free_elsewhere(SIDE))
        self.assertTrue(_free_elsewhere(BACK))

    def test_a_failed_wait_releases_what_it_already_took(self):
        self._hold_elsewhere(SIDE)

        with (
            patch.object(lock_config_sync_uc, "SYNC_LOCK_WAIT_SECONDS", 0.05),
            self.assertRaises(LockBusy),
            hold_lock_sync([SIDE, BACK]),
        ):
            pass

        self.assertTrue(_free_elsewhere(BACK))

    def test_update_with_nested_pushes_and_clears_finishes_and_leaves_nothing_held(self):
        code = self._pushed_code([BACK, SIDE])

        door_codes_uc.update_door_code(
            code=self._fresh(code),
            changes={"code": "5555", "lock_entity_ids": [BACK, FRONT]},
            actor_user=self.user,
            zwavejs=self.gateway,
        )

        self.assertEqual(self._lock_codes(12), {1: "5555"})
        self.assertEqual(self._lock_codes(13), {})
        self.assertEqual(self._lock_codes(14), {1: "5555"})
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        for lock_entity_id in (BACK, SIDE, FRONT):
            self.assertTrue(_free_elsewhere(lock_entity_id), lock_entity_id)

    def test_delete_with_nested_clears_finishes_and_leaves_nothing_held(self):
        code = self._pushed_code([SIDE, BACK])

        door_codes_uc.delete_door_code(code=self._fresh(code), actor_user=self.user, zwavejs=self.gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertCountEqual(self._cc99("clear"), [(12, [1]), (13, [1])])
        for lock_entity_id in (BACK, SIDE):
            self.assertTrue(_free_elsewhere(lock_entity_id), lock_entity_id)


class LockOrderTests(_LockingTestBase):
    def test_update_takes_every_lock_it_touches_in_sorted_order(self):
        code = self._pushed_code([SIDE])

        with _recording_acquires() as keys:
            door_codes_uc.update_door_code(
                code=self._fresh(code),
                changes={"lock_entity_ids": [SIDE, FRONT, BACK]},
                actor_user=self.user,
                zwavejs=self.gateway,
            )

        self.assertEqual(keys[:3], [BACK, FRONT, SIDE])

    def test_delete_also_takes_a_lock_only_a_failed_clear_or_unconfirmed_push_points_at(self):
        code = self._pushed_code([SIDE])
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id=FRONT, slot_index=2, reason="timeout", pin=PIN
        )
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=BACK,
            slot_index=3,
            exc=ZwavejsCommandError("driver TimeoutError after 10.0s"),
            expected_pin=PIN,
        )

        with _recording_acquires() as keys:
            door_codes_uc.delete_door_code(code=self._fresh(code), actor_user=self.user, zwavejs=self.gateway)

        self.assertEqual(keys[:3], [BACK, FRONT, SIDE])

    def test_a_lock_added_while_waiting_is_taken_before_the_update_goes_ahead(self):
        code = self._pushed_code([BACK])
        holder = self._hold_elsewhere(BACK)

        def another_save_adds_side():
            DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=SIDE)
            holder.release()

        with _when_waiting_on(BACK, another_save_adds_side), _recording_acquires() as keys:
            door_codes_uc.update_door_code(
                code=self._fresh(code), changes={"label": "Cleaner"}, actor_user=self.user, zwavejs=self.gateway
            )

        # BACK busy, then BACK alone, then BACK and SIDE together once SIDE showed up.
        self.assertEqual(keys, [BACK, BACK, BACK, SIDE])
        self.assertTrue(_free_elsewhere(SIDE))


class _GetHookGateway(FakeGateway):
    """Runs ``on_get`` before answering each CC 99 ``get``."""

    on_get = None

    def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
        if command_class == 99 and method_name == "get" and self.on_get is not None:
            self.on_get(node_id, args)
        return super().invoke_cc_api(
            node_id=node_id,
            command_class=command_class,
            method_name=method_name,
            args=args,
            timeout_seconds=timeout_seconds,
        )


class ClaimedSlotRecheckTests(_LockingTestBase):
    """A slot another code takes between the readback and the clear is left alone (#131 comment)."""

    def setUp(self):
        super().setUp()
        self.gateway = _GetHookGateway(usersNumber=5, cache_updates_on_set=True)
        self.other = self._pending_code([], pin="9999")

    def _other_code_takes(self, slot_index: int):
        def take(node_id, args):
            if args == [slot_index]:
                DoorCodeLockAssignment.objects.update_or_create(
                    door_code=self.other, lock_entity_id=BACK, defaults={"slot_index": slot_index}
                )

        return take

    def test_unconfirmed_slot_cleanup_rechecks_right_before_the_clear(self):
        code = self._pending_code([BACK])
        self.gateway._lock_codes[(12, 2)] = PIN
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id=BACK, slot_index=2, reason="timeout", pin=PIN
        )
        self.gateway.on_get = self._other_code_takes(2)

        cleared, failed = lock_push_uc.clear_unconfirmed_slots_holding_pin(
            door_code=code, pin=PIN, lock_entity_ids=[BACK], zwavejs=self.gateway
        )

        self.assertEqual((cleared, failed), ([], []))
        self.assertEqual(self._cc99("clear"), [])
        self.assertEqual(self._lock_codes(12), {2: PIN})

    def test_failed_clear_retry_rechecks_right_before_the_clear(self):
        code = self._pending_code([BACK])
        self.gateway._lock_codes[(12, 2)] = PIN
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=BACK,
            slot_index=2,
            exc=ZwavejsCommandError("driver TimeoutError after 10.0s"),
            expected_pin=PIN,
        )
        self.gateway.on_get = self._other_code_takes(2)

        still_failing = lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=self.gateway)

        self.assertEqual(still_failing, [])
        self.assertEqual(self._cc99("clear"), [])
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
        resolved = DoorCodeEvent.objects.filter(door_code=code, metadata__action="clear_resolved").get()
        self.assertEqual(resolved.metadata["outcome"], "tracked")


class FailedClearRetryLockTests(_LockingTestBase):
    def _failed_clear(self) -> DoorCode:
        code = self._pushed_code([BACK])
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=BACK,
            slot_index=1,
            exc=ZwavejsCommandError("driver TimeoutError after 10.0s"),
            expected_pin=PIN,
        )
        return code

    def test_retry_waits_for_the_lock(self):
        code = self._failed_clear()
        holder = self._hold_elsewhere(BACK)

        with _when_waiting_on(BACK, holder.release) as waited:
            still_failing = lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=self.gateway)

        self.assertTrue(waited)
        self.assertEqual(still_failing, [])
        self.assertEqual(self._cc99("clear"), [(12, [1])])

    def test_retry_on_a_lock_still_busy_counts_as_still_failing(self):
        code = self._failed_clear()
        self._hold_elsewhere(BACK)

        with patch.object(lock_config_sync_uc, "SYNC_LOCK_WAIT_SECONDS", 0.05):
            still_failing = lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=self.gateway)

        self.assertEqual([(f.lock_entity_id, f.slot_index) for f in still_failing], [(BACK, 1)])
        self.assertIn("LockBusy", still_failing[0].reason)
        self.assertEqual(self.gateway.invoke_calls, [])
        self.assertEqual(len(lock_push_uc.unresolved_clear_failures(door_code=code)), 1)
        code.refresh_from_db()
        self.assertEqual(code.push_attempt_count, 1)

    def test_clear_helper_waits_for_the_lock_when_the_caller_doesnt_hold_it(self):
        holder = self._hold_elsewhere(BACK)

        with _when_waiting_on(BACK, holder.release) as waited:
            lock_config_sync_uc.clear_lock_user_code_slot(lock_entity_id=BACK, slot_index=1, zwavejs=self.gateway)

        self.assertTrue(waited)
        self.assertEqual(self._cc99("clear"), [(12, [1])])
        self.assertTrue(_free_elsewhere(BACK))


class LockBusyApiTests(_LockingTestBase, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def test_patch_returns_409_while_another_operation_holds_the_lock(self):
        code = self._pushed_code([BACK])
        self._hold_elsewhere(BACK)

        with (
            patch.object(lock_config_sync_uc, "SYNC_LOCK_WAIT_SECONDS", 0.05),
            patch("locks.views.door_codes.default_zwavejs_gateway", self.gateway),
        ):
            response = self.client.patch(
                reverse("door-code-detail", args=[code.id]),
                {"label": "Cleaner", "reauth_password": "pass"},
                format="json",
            )

        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn(f"Another operation on {BACK} is still running", response.json()["error"]["message"])
        code.refresh_from_db()
        self.assertEqual(code.label, "")

    def test_delete_returns_409_while_another_operation_holds_the_lock(self):
        code = self._pushed_code([BACK])
        self._hold_elsewhere(BACK)

        with (
            patch.object(lock_config_sync_uc, "SYNC_LOCK_WAIT_SECONDS", 0.05),
            patch("locks.views.door_codes.default_zwavejs_gateway", self.gateway),
        ):
            response = self.client.delete(
                reverse("door-code-detail", args=[code.id]), {"reauth_password": "pass"}, format="json"
            )

        self.assertEqual(response.status_code, 409, response.content)
        self.assertTrue(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self.gateway.invoke_calls, [])


class SyncReleasesAfterCommitTests(EncryptionTestMixin, TransactionTestCase):
    """``sync_lock_config`` lets go of ``lock_sync:`` only once its transaction committed."""

    LOCK = "lock.front_door"  # node 5, as in the sync API tests

    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 5}},
            source="home_assistant",
        )

    def _single_slot_gateway(self) -> FakeZwavejsGateway:
        status_vid = {"commandClass": 99, "property": "userIdStatus", "propertyKey": 1}
        code_vid = {"commandClass": 99, "property": "userCode", "propertyKey": 1}
        users_vid = {"commandClass": 99, "property": "usersNumber"}
        return FakeZwavejsGateway(
            value_ids=[users_vid, status_vid, code_vid],
            values={
                (5, _value_id_key(users_vid)): 1,
                (5, _value_id_key(status_vid)): 1,
                (5, _value_id_key(code_vid)): "1234",
            },
        )

    def _sync(self, gateway) -> lock_config_sync_uc.SyncResult:
        return lock_config_sync_uc.sync_lock_config(
            lock_entity_id=self.LOCK, target_user=self.user, actor_user=self.admin, zwavejs=gateway
        )

    def test_the_lock_is_released_after_the_sync_commits(self):
        seen: dict[str, object] = {}
        real_release = lock_config_sync_uc._release_sync_lock

        def release(*, lock_key, lock_id):
            seen["in_atomic_block"] = connection.in_atomic_block
            if _is_postgres():
                other = connections.create_connection(DEFAULT_DB_ALIAS)
                try:
                    with other.cursor() as cursor:
                        cursor.execute(
                            "SELECT count(*) FROM door_code_lock_assignments WHERE lock_entity_id = %s", [self.LOCK]
                        )
                        seen["assignments_seen_elsewhere"] = cursor.fetchone()[0]
                finally:
                    other.close()
            real_release(lock_key=lock_key, lock_id=lock_id)

        with patch.object(lock_config_sync_uc, "_release_sync_lock", release):
            result = self._sync(self._single_slot_gateway())

        self.assertEqual(result.created, 1)
        self.assertIs(seen["in_atomic_block"], False)
        if _is_postgres():
            # Another connection (the next push) already sees what the sync wrote.
            self.assertEqual(seen["assignments_seen_elsewhere"], 1)
        self.assertTrue(_free_elsewhere(self.LOCK))

    def test_the_lock_is_released_when_the_sync_fails(self):
        with self.assertRaises(lock_config_sync_uc.InvalidRequest):
            self._sync(FakeZwavejsGateway(value_ids=[], values={}))

        self.assertTrue(_free_elsewhere(self.LOCK))
        self.assertFalse(DoorCodeLockAssignment.objects.exists())

    def test_a_busy_lock_still_rejects_the_sync(self):
        holder = _OtherHolder(self.LOCK).acquire()
        self.addCleanup(holder.release)

        with self.assertRaises(lock_config_sync_uc.SyncInProgress):
            self._sync(self._single_slot_gateway())

        self.assertFalse(DoorCodeLockAssignment.objects.exists())
