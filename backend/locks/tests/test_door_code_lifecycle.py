"""Issue #145: a door code's PIN is only on its locks between its ``start_at`` and ``end_at``.

There's no freezegun here, so times are relative to now and the clock passing a
code's ``start_at`` or ``end_at`` is done by moving the date on the row.
Imports of what this issue adds stay inside the tests, so on a branch without it
each test fails on its own instead of the whole module failing to import.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from integrations_zwavejs.manager import ZwavejsCommandError
from rest_framework.test import APITestCase

from alarm.crypto import SettingsEncryption
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.serializers import DoorCodeCreateSerializer, DoorCodeSerializer, DoorCodeUpdateSerializer
from locks.tests.test_door_code_locking import _OtherHolder, _when_waiting_on
from locks.tests.test_lock_push import ClearFailingGateway, FakeGateway, _TwoLockUpdateTestBase
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_config_sync as lock_config_sync_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.lock_push import PushSuperseded


def _timeouts(count: int = 3) -> list[Exception]:
    return [ZwavejsCommandError("driver TimeoutError after 5.0s") for _ in range(count)]


def _iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


class CodeLifecyclePredicateTests(SimpleTestCase):
    """The shared predicates only look at the dates and the use count."""

    def setUp(self):
        self.now = timezone.now()

    def _code(self, **kwargs) -> DoorCode:
        return DoorCode(code_type=kwargs.pop("code_type", DoorCode.CodeType.TEMPORARY), **kwargs)

    def test_end_at_is_exclusive(self):
        from locks.use_cases.code_lifecycle import is_expired

        self.assertTrue(is_expired(self._code(end_at=self.now), now=self.now))
        self.assertTrue(is_expired(self._code(end_at=self.now - timedelta(seconds=1)), now=self.now))
        self.assertFalse(is_expired(self._code(end_at=self.now + timedelta(microseconds=1)), now=self.now))
        self.assertFalse(is_expired(self._code(end_at=None), now=self.now))

    def test_start_at_is_inclusive(self):
        from locks.use_cases.code_lifecycle import is_started

        self.assertTrue(is_started(self._code(start_at=self.now), now=self.now))
        self.assertTrue(is_started(self._code(start_at=None), now=self.now))
        self.assertFalse(is_started(self._code(start_at=self.now + timedelta(microseconds=1)), now=self.now))

    def test_exhausted_from_max_uses_or_a_used_one_time_code(self):
        from locks.use_cases.code_lifecycle import is_exhausted

        self.assertFalse(is_exhausted(self._code(max_uses=None, uses_count=10)))
        self.assertFalse(is_exhausted(self._code(max_uses=3, uses_count=2)))
        self.assertTrue(is_exhausted(self._code(max_uses=3, uses_count=3)))
        self.assertFalse(is_exhausted(self._code(code_type=DoorCode.CodeType.ONE_TIME, uses_count=0)))
        self.assertTrue(is_exhausted(self._code(code_type=DoorCode.CodeType.ONE_TIME, uses_count=1)))

    def test_validity(self):
        from locks.use_cases.code_lifecycle import validity

        hour = timedelta(hours=1)
        self.assertEqual(validity(self._code(), now=self.now), "valid")
        self.assertEqual(validity(self._code(start_at=self.now + hour), now=self.now), "scheduled")
        self.assertEqual(validity(self._code(end_at=self.now), now=self.now), "expired")
        self.assertEqual(validity(self._code(max_uses=1, uses_count=1), now=self.now), "exhausted")
        # Expired wins over used up and not started.
        self.assertEqual(
            validity(self._code(start_at=self.now, end_at=self.now, max_uses=1, uses_count=1), now=self.now),
            "expired",
        )

    def test_keyed_on_the_dates_not_the_type_or_source(self):
        from locks.use_cases.code_lifecycle import is_expired, is_started

        # Lock sync can turn a temporary manual code into a permanent synced one with its dates.
        synced = self._code(
            code_type=DoorCode.CodeType.PERMANENT,
            source=DoorCode.Source.SYNCED,
            start_at=self.now + timedelta(hours=1),
            end_at=self.now - timedelta(hours=1),
        )
        self.assertTrue(is_expired(synced, now=self.now))
        self.assertFalse(is_started(synced, now=self.now))


class _LifecycleTestBase(_TwoLockUpdateTestBase):
    def _enforce(self, gateway: FakeGateway) -> int:
        from locks.tasks import enforce_door_code_validity

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            return enforce_door_code_validity()

    def _push_pending(self, gateway: FakeGateway) -> int:
        from locks.tasks import push_pending_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            return push_pending_door_codes()

    def _temporary_code(self, lock_entity_ids: list[str], **kwargs) -> tuple[DoorCode, ClearFailingGateway]:
        kwargs.setdefault("end_at", timezone.now() + timedelta(days=1))
        return self._pushed_code(lock_entity_ids, code_type=DoorCode.CodeType.TEMPORARY, **kwargs)

    @staticmethod
    def _move(code: DoorCode, **fields) -> DoorCode:
        """The clock passing a date, done by moving the date on the row."""
        DoorCode.objects.filter(id=code.id).update(**fields)
        return DoorCode.objects.get(id=code.id)

    @staticmethod
    def _ago(**kwargs):
        return timezone.now() - timedelta(**kwargs)

    @staticmethod
    def _from_now(**kwargs):
        return timezone.now() + timedelta(**kwargs)


class ExpiryTests(_LifecycleTestBase):
    """Expired codes come off their locks through the same path a user's deactivate takes."""

    def test_scheduler_retires_an_expired_code_and_clears_every_lock(self):
        code, gateway = self._temporary_code([self.BACK, self.SIDE])
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self._move(code, end_at=self._ago(minutes=1))

        self.assertEqual(self._enforce(gateway), 1)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertCountEqual(self._calls(gateway, "clear"), [(12, [1]), (13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: None})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        event = self._updated_event(code)
        self.assertEqual(event.metadata["updated_fields"], ["is_active"])
        self.assertEqual(event.metadata["reason"], "expired")
        self.assertIsNone(event.user)

        # Retired once: the next tick leaves it alone.
        gateway.invoke_calls.clear()
        self.assertEqual(self._enforce(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

    def test_an_end_at_of_exactly_now_is_expired(self):
        code, gateway = self._temporary_code([self.BACK])
        now = timezone.now()
        code = self._move(code, end_at=now)

        retired = door_codes_uc.retire_door_code(code=code, reason="expired", zwavejs=gateway, now=now)

        self.assertIsNotNone(retired)
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})

    def test_a_code_that_has_not_expired_is_left_alone(self):
        code, gateway = self._temporary_code([self.BACK])
        now = timezone.now()
        code = self._move(code, end_at=now + timedelta(seconds=1))

        self.assertIsNone(door_codes_uc.retire_door_code(code=code, reason="expired", zwavejs=gateway, now=now))
        self.assertEqual(self._enforce(gateway), 0)

        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})

    def test_a_failed_clear_goes_pending_and_the_scheduler_finishes_it(self):
        code, gateway = self._temporary_code([self.BACK, self.SIDE])
        self._move(code, end_at=self._ago(minutes=1))
        gateway.clear_fails_on = {12}

        self.assertEqual(self._enforce(gateway), 1)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: None})
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", code.last_push_error)
        [failure] = lock_push_uc.unresolved_clear_failures(door_code=code)
        self.assertEqual((failure.lock_entity_id, failure.slot_index), (self.BACK, 1))
        self.assertEqual(failure.expected_pin, self.PIN)
        self.assertEqual(
            self._updated_event(code).metadata["failed_slot_clears"][0]["lock_entity_id"],
            self.BACK,
        )

        # The validity task doesn't retry it; it's already off.
        gateway.invoke_calls.clear()
        self.assertEqual(self._enforce(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

        # push_pending_door_codes' clear retry finishes it, and nothing is pushed back.
        gateway.clear_fails_on = set()
        self._push_pending(gateway)

        code.refresh_from_db()
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: None})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_an_unconfirmed_slot_is_read_back_and_cleared(self):
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True, get_responses={13: _timeouts()})
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            end_at=self._from_now(days=1),
            lock_entity_ids=[self.BACK, self.SIDE],
            actor_user=self.user,
            zwavejs=gateway,
        )
        # The PIN landed on Side but every readback there timed out.
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: None})
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [self.SIDE])
        self._move(code, end_at=self._ago(minutes=1))
        gateway.invoke_calls.clear()

        self._enforce(gateway)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertCountEqual(self._calls(gateway, "clear"), [(12, [1]), (13, [1])])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [])
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_a_busy_lock_does_not_raise_and_the_next_tick_retires_it(self):
        code, gateway = self._temporary_code([self.BACK])
        self._move(code, end_at=self._ago(minutes=1))
        holder = _OtherHolder(self.BACK).acquire()
        self.addCleanup(holder.release)

        with patch.object(lock_config_sync_uc, "SYNC_LOCK_WAIT_SECONDS", 0.05):
            self.assertEqual(self._enforce(gateway), 0)

        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(gateway.invoke_calls, [])

        holder.release()
        self.assertEqual(self._enforce(gateway), 1)
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})

    def test_one_bad_code_does_not_stop_the_others(self):
        first, gateway = self._temporary_code([self.BACK])
        second = door_codes_uc.create_door_code(
            user=self.user,
            raw_code="5678",
            code_type=DoorCode.CodeType.TEMPORARY,
            end_at=self._from_now(days=1),
            lock_entity_ids=[self.SIDE],
            actor_user=self.user,
            zwavejs=gateway,
        )
        self._move(first, end_at=self._ago(minutes=2))
        self._move(second, end_at=self._ago(minutes=1))
        real = door_codes_uc.retire_door_code

        def retire(*, code, **kwargs):
            if code.id == first.id:
                raise RuntimeError("boom")
            return real(code=code, **kwargs)

        with patch.object(door_codes_uc, "retire_door_code", retire):
            self.assertEqual(self._enforce(gateway), 1)

        self.assertTrue(DoorCode.objects.get(id=first.id).is_active)
        self.assertFalse(DoorCode.objects.get(id=second.id).is_active)

    def test_end_at_moved_later_while_waiting_for_the_lock_means_no_retire(self):
        code, gateway = self._temporary_code([self.BACK])
        now = timezone.now()
        stale = self._move(code, end_at=now - timedelta(minutes=1))
        holder = _OtherHolder(self.BACK).acquire()
        self.addCleanup(holder.release)

        def extend_then_let_go():
            # A save that was holding the lock moved end_at later.
            DoorCode.objects.filter(id=code.id).update(end_at=now + timedelta(days=1))
            holder.release()

        with _when_waiting_on(self.BACK, extend_then_let_go) as fired:
            result = door_codes_uc.retire_door_code(code=stale, reason="expired", zwavejs=gateway, now=now)

        self.assertEqual(fired, [f"lock_sync:{self.BACK}"])
        self.assertIsNone(result)
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertFalse(DoorCodeEvent.objects.filter(door_code=code, metadata__reason="expired").exists())

    def test_a_code_deleted_while_waiting_is_left_alone(self):
        code, gateway = self._temporary_code([self.BACK])
        stale = self._move(code, end_at=self._ago(minutes=1))
        DoorCode.objects.filter(id=code.id).delete()

        self.assertIsNone(door_codes_uc.retire_door_code(code=stale, reason="expired", zwavejs=gateway))

    def test_a_synced_code_with_an_end_at_is_retired_too(self):
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True)
        gateway._lock_codes[(12, 3)] = self.PIN
        code = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            end_at=self._ago(minutes=1),
            push_state=DoorCode.PushState.PUSHED,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK, slot_index=3)

        self.assertEqual(self._enforce(gateway), 1)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(self._calls(gateway, "clear"), [(12, [3])])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})

    def test_a_one_time_code_with_an_end_at_is_retired(self):
        code, gateway = self._pushed_code(
            [self.BACK], code_type=DoorCode.CodeType.ONE_TIME, end_at=self._from_now(days=1)
        )
        self._move(code, end_at=self._ago(minutes=1))

        self.assertEqual(self._enforce(gateway), 1)

        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})

    def test_an_expired_code_waiting_for_a_slot_is_not_pushed_by_the_retry_task(self):
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            end_at=self._from_now(days=1),
            lock_entity_ids=[self.BACK],
            actor_user=self.user,
        )
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self._move(code, end_at=self._ago(minutes=1))
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True)

        self.assertEqual(self._push_pending(gateway), 0)

        self.assertEqual(gateway.invoke_calls, [])

    def test_retry_on_an_expired_code_that_is_still_on_retires_it(self):
        code, gateway = self._temporary_code([self.BACK])
        # The push gave up, and it expired before the scheduler turned it off.
        DoorCode.objects.filter(id=code.id).update(
            push_state=DoorCode.PushState.FAILED, push_attempt_count=5, last_push_error="gave up"
        )
        code = self._move(code, end_at=self._ago(minutes=1))

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._updated_event(code).metadata["reason"], "expired")
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_retry_on_an_expired_code_whose_clear_fails_leaves_it_off_and_pending(self):
        code, gateway = self._temporary_code([self.BACK])
        DoorCode.objects.filter(id=code.id).update(push_state=DoorCode.PushState.FAILED)
        code = self._move(code, end_at=self._ago(minutes=1))
        gateway.clear_fails_on = {12}

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", code.last_push_error)
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_an_expired_code_is_never_pushed(self):
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            end_at=self._from_now(days=1),
            lock_entity_ids=[self.BACK],
            actor_user=self.user,
        )
        code = self._move(code, end_at=self._ago(minutes=1))
        gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)

        stale = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
        self.assertEqual(lock_push_uc.push_door_code_to_assigned_locks(door_code=stale, zwavejs=gateway), ([], []))
        with self.assertRaises(PushSuperseded):
            lock_push_uc.push_door_code_to_lock(door_code=stale, lock_entity_id=self.BACK, zwavejs=gateway)
        self.assertEqual(self._calls(gateway, "set"), [])


class StartTests(_LifecycleTestBase):
    """A code goes on its locks at its start_at and not before."""

    def _scheduled_code(self, lock_entity_ids: list[str]) -> tuple[DoorCode, ClearFailingGateway]:
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True)
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            start_at=self._from_now(hours=2),
            end_at=self._from_now(days=1),
            lock_entity_ids=lock_entity_ids,
            actor_user=self.user,
            zwavejs=gateway,
        )
        return code, gateway

    def test_a_future_code_is_not_pushed_until_its_start(self):
        code, gateway = self._scheduled_code([self.BACK, self.SIDE])

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: None})
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)

        # Neither scheduler task pushes it early.
        self.assertEqual(self._push_pending(gateway), 0)
        self.assertEqual(self._enforce(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

        self._move(code, start_at=self._ago(seconds=5))
        self.assertEqual(self._enforce(gateway), 1)

        code.refresh_from_db()
        self.assertCountEqual(self._calls(gateway, "set"), [(12, [1, 1, self.PIN]), (13, [1, 1, self.PIN])])
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

        gateway.invoke_calls.clear()
        self.assertEqual(self._enforce(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

    def test_a_start_push_that_does_not_land_is_left_to_the_retry_task(self):
        code, gateway = self._scheduled_code([self.BACK])
        self._move(code, start_at=self._ago(seconds=5))
        holder = _OtherHolder(self.BACK).acquire()
        self.addCleanup(holder.release)

        self._enforce(gateway)
        self._enforce(gateway)

        self.assertEqual(self._calls(gateway, "set"), [])
        code.refresh_from_db()
        self.assertGreaterEqual(code.last_push_attempt_at, code.start_at)
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)

        holder.release()
        self.assertEqual(self._enforce(gateway), 0)
        self._push_pending(gateway)
        self.assertEqual(self._calls(gateway, "set"), [(12, [1, 1, self.PIN])])
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, DoorCode.PushState.PUSHED)

    def test_a_scheduler_push_is_superseded_when_start_at_moves_into_the_future(self):
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            lock_entity_ids=[self.BACK],
            actor_user=self.user,
        )
        gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)
        # The scheduler loaded the code, then a save moved its start later
        # before the push got the lock.
        stale = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
        self._move(code, start_at=self._from_now(hours=1))

        with self.assertRaises(PushSuperseded):
            lock_push_uc.push_door_code_to_lock(door_code=stale, lock_entity_id=self.BACK, zwavejs=gateway)
        self.assertEqual(lock_push_uc.push_door_code_to_assigned_locks(door_code=stale, zwavejs=gateway), ([], []))

        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._slots(code), {self.BACK: None})

    def test_an_early_pushed_code_is_withdrawn_and_pushed_again_at_its_start(self):
        # Pushed before start_at was enforced.
        code, gateway = self._temporary_code([self.BACK, self.SIDE])
        self._move(code, start_at=self._from_now(hours=1))

        self.assertEqual(self._enforce(gateway), 1)

        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertCountEqual(self._calls(gateway, "clear"), [(12, [1]), (13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: None})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        event = DoorCodeEvent.objects.filter(door_code=code, metadata__action="withdrawn").get()
        self.assertEqual(event.metadata["reason"], "not_started")
        self.assertCountEqual(
            event.metadata["cleared_slots"],
            [{"lock_entity_id": self.BACK, "slot_index": 1}, {"lock_entity_id": self.SIDE, "slot_index": 1}],
        )

        gateway.invoke_calls.clear()
        self.assertEqual(self._enforce(gateway), 0)
        self.assertEqual(self._push_pending(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

        # Its start comes after the early push and the withdraw.
        self._move(code, start_at=timezone.now())
        self._enforce(gateway)
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, DoorCode.PushState.PUSHED)

    def test_an_early_pushed_code_whose_clear_fails_is_retried_but_not_pushed(self):
        code, gateway = self._temporary_code([self.BACK])
        self._move(code, start_at=self._from_now(hours=1))
        gateway.clear_fails_on = {12}

        self._enforce(gateway)

        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", code.last_push_error)

        # Left to the clear retry, not tried again every minute.
        gateway.invoke_calls.clear()
        self.assertEqual(self._enforce(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

        gateway.clear_fails_on = set()
        self._push_pending(gateway)

        code.refresh_from_db()
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertTrue(code.is_active)
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])

    def test_a_withdraw_waiting_on_a_busy_lock_does_not_raise(self):
        code, gateway = self._temporary_code([self.BACK])
        self._move(code, start_at=self._from_now(hours=1))
        holder = _OtherHolder(self.BACK).acquire()
        self.addCleanup(holder.release)

        with patch.object(lock_config_sync_uc, "SYNC_LOCK_WAIT_SECONDS", 0.05):
            self.assertEqual(self._enforce(gateway), 0)

        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})

    def test_retry_on_a_code_that_has_not_started_is_refused(self):
        code, gateway = self._scheduled_code([self.BACK])

        with self.assertRaises(door_codes_uc.DoorCodeNotStarted):
            door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(gateway.invoke_calls, [])

    def _withdraw_that_hit_the_cap(self) -> tuple[DoorCode, ClearFailingGateway]:
        """An early-pushed code whose withdraw clear kept failing until the scheduler gave up."""
        code, gateway = self._temporary_code([self.BACK])
        self._move(code, start_at=self._from_now(hours=1))
        gateway.clear_fails_on = {12}
        self._enforce(gateway)
        with patch("locks.tasks._get_push_max_attempts", return_value=2):
            self._push_pending(gateway)
            self._push_pending(gateway)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        return code, gateway

    def test_retry_clears_a_withdraw_that_hit_the_attempt_cap(self):
        code, gateway = self._withdraw_that_hit_the_cap()

        # Nothing else picks it up: the PIN would keep working until its start.
        # The code-level cap only counts clear retries now and is read every tick
        # (issue #126), so it stays at the 2 that failed the code.
        gateway.clear_fails_on = set()
        gateway.invoke_calls.clear()
        self.assertEqual(self._enforce(gateway), 0)
        with patch("locks.tasks._get_push_max_attempts", return_value=2):
            self.assertEqual(self._push_pending(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(code.last_push_error, "")
        self.assertEqual(code.push_attempt_count, 0)

        # Nothing left to clear, so another Retry is refused, and it goes on at its start.
        with self.assertRaises(door_codes_uc.DoorCodeNotStarted):
            door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)
        self._move(code, start_at=timezone.now())
        self._enforce(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})

    def test_retry_of_a_withdraw_that_still_fails_goes_back_to_the_scheduler(self):
        code, gateway = self._withdraw_that_hit_the_cap()

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", code.last_push_error)
        self.assertEqual(self._calls(gateway, "set"), [])

        # Re-armed, so the clear retry finishes it once the lock answers.
        gateway.clear_fails_on = set()
        self._push_pending(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_retry_withdraws_a_slot_a_scheduled_code_still_holds(self):
        # Pushed early, and Retry got there before the validity task.
        code, gateway = self._temporary_code([self.BACK])
        code = self._move(code, start_at=self._from_now(hours=1))

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)

    def test_withdraw_with_nothing_to_do_does_not_take_the_locks(self):
        # Its slot's clear failed and is left to the clear retries.
        code, gateway = self._temporary_code([self.BACK])
        self._move(code, start_at=self._from_now(hours=1))
        gateway.clear_fails_on = {12}
        self._enforce(gateway)

        with patch.object(door_codes_uc, "_hold_door_code_locks", wraps=door_codes_uc._hold_door_code_locks) as held:
            self.assertEqual(self._enforce(gateway), 0)

        held.assert_not_called()

    def test_a_scheduled_code_with_only_settled_unconfirmed_attempts_is_not_withdrawn_again(self):
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True, get_responses={13: _timeouts()})
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            end_at=self._from_now(days=1),
            lock_entity_ids=[self.SIDE],
            actor_user=self.user,
            zwavejs=gateway,
        )
        # Only an unconfirmed attempt slot, no tracked one, so the query has to find it.
        self.assertEqual(self._slots(code), {self.SIDE: None})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [self.SIDE])
        self._move(code, start_at=self._from_now(hours=1))
        self.assertEqual(self._enforce(gateway), 1)
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [])

        # Its push_unconfirmed event is still on record, but settled.
        with patch.object(door_codes_uc, "withdraw_door_code") as withdraw:
            self.assertEqual(self._enforce(gateway), 0)
        withdraw.assert_not_called()

    def test_a_scheduled_code_whose_attempt_a_clear_retry_read_back_empty_is_not_withdrawn_again(self):
        # Issues #128, #152: a clear_resolved with slot_empty settles the attempt.
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.TEMPORARY,
            is_active=True,
            start_at=self._from_now(hours=1),
            end_at=self._from_now(days=1),
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.SIDE)
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id=self.SIDE, slot_index=1, reason="timeout", pin=self.PIN, slot_available=True
        )
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=self.SIDE,
            slot_index=1,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin=self.PIN,
            unconfirmed=True,
            slot_available=True,
        )
        lock_push_uc.forget_cleared_slot(
            door_code=code, lock_entity_id=self.SIDE, slot_index=1, outcome="not_holding_pin", slot_empty=True
        )
        self.assertEqual(lock_push_uc.slots_to_withdraw(door_code=code), [])

        with patch.object(door_codes_uc, "withdraw_door_code") as withdraw:
            self.assertEqual(self._enforce(FakeGateway(usersNumber=5)), 0)
        withdraw.assert_not_called()


class StartAtUpdateTests(_LifecycleTestBase, APITestCase):
    """Moving start_at across now on an update takes the code off its locks or puts it on."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def _patch(self, code: DoorCode, gateway: FakeGateway, body: dict, *, status: int = 200) -> dict:
        url = reverse("door-code-detail", args=[code.id])
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.patch(url, {**body, "reauth_password": "pass"}, format="json")
        self.assertEqual(response.status_code, status, response.content)
        return response.json()

    def test_moving_start_at_into_the_future_takes_it_off_its_locks(self):
        code, gateway = self._temporary_code([self.BACK, self.SIDE])

        body = self._patch(code, gateway, {"start_at": _iso(self._from_now(hours=2))})

        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertCountEqual(self._calls(gateway, "clear"), [(12, [1]), (13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: None})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(body["data"]["validity"], "scheduled")

    def test_moving_start_at_into_the_past_pushes_it(self):
        code, gateway = self._temporary_code([self.BACK], start_at=self._from_now(hours=2))
        self.assertEqual(self._slots(code), {self.BACK: None})

        body = self._patch(code, gateway, {"start_at": _iso(self._ago(minutes=1))})

        self.assertEqual(self._calls(gateway, "set"), [(12, [1, 1, self.PIN])])
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(body["data"]["push_state"], DoorCode.PushState.PUSHED)
        self.assertEqual(body["data"]["validity"], "valid")

    def test_moving_start_at_within_the_future_or_the_past_does_not_touch_the_locks(self):
        scheduled, gateway = self._temporary_code([self.BACK], start_at=self._from_now(hours=2))
        self._patch(scheduled, gateway, {"start_at": _iso(self._from_now(hours=3))})
        self.assertEqual(gateway.invoke_calls, [])

        started, gateway = self._temporary_code([self.SIDE], start_at=self._ago(hours=2))
        self._patch(started, gateway, {"start_at": _iso(self._ago(hours=3))})
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._slots(started), {self.SIDE: 1})

    def test_moving_start_at_into_the_future_clears_an_unconfirmed_slot(self):
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True, get_responses={13: _timeouts()})
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            end_at=self._from_now(days=1),
            lock_entity_ids=[self.BACK, self.SIDE],
            actor_user=self.user,
            zwavejs=gateway,
        )
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})

        self._patch(code, gateway, {"start_at": _iso(self._from_now(hours=2))})

        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [])

    def test_retry_through_the_api_returns_409_before_the_start(self):
        code, gateway = self._temporary_code([self.BACK], start_at=self._from_now(hours=2))

        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.post(reverse("door-code-push", args=[code.id]))

        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn("hasn't started", response.json()["error"]["message"])
        self.assertEqual(gateway.invoke_calls, [])

    def test_retry_through_the_api_clears_a_failed_withdraw_before_the_start(self):
        code, gateway = self._temporary_code([self.BACK])
        self._move(code, start_at=self._from_now(hours=1))
        gateway.clear_fails_on = {12}
        self._enforce(gateway)
        DoorCode.objects.filter(id=code.id).update(push_state=DoorCode.PushState.FAILED)
        gateway.clear_fails_on = set()

        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.post(reverse("door-code-push", args=[code.id]))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(response.json()["data"]["push_state"], DoorCode.PushState.PENDING)


class ValidationTests(_LifecycleTestBase, APITestCase):
    """The API won't take a past end_at or turn on an expired code (issue #145)."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def _create_body(self, **overrides) -> dict:
        return {
            "user_id": str(self.user.id),
            "code": self.PIN,
            "code_type": DoorCode.CodeType.TEMPORARY,
            "lock_entity_ids": [self.BACK],
            "reauth_password": "pass",
            **overrides,
        }

    def _expired_code(self, *, is_active: bool = False) -> tuple[DoorCode, ClearFailingGateway]:
        code, gateway = self._temporary_code([self.BACK])
        code = self._move(code, end_at=self._ago(hours=1))
        if not is_active:
            door_codes_uc.retire_door_code(code=code, reason="expired", zwavejs=gateway)
            code.refresh_from_db()
            self.assertFalse(code.is_active)
        gateway.invoke_calls.clear()
        return code, gateway

    def _patch(self, code: DoorCode, gateway: FakeGateway, body: dict):
        url = reverse("door-code-detail", args=[code.id])
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            return self.client.patch(url, {**body, "reauth_password": "pass"}, format="json")

    def test_create_rejects_a_past_end_at(self):
        response = self.client.post(
            reverse("door-codes"), self._create_body(end_at=_iso(self._ago(minutes=1))), format="json"
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("end_at", response.json()["error"]["details"])
        self.assertFalse(DoorCode.objects.exists())

    def test_create_end_at_edges(self):
        now = timezone.now()

        def valid(end_at) -> bool:
            serializer = DoorCodeCreateSerializer(data=self._create_body(end_at=_iso(end_at)), context={"now": now})
            return serializer.is_valid()

        self.assertFalse(valid(now))  # exclusive: expired at end_at itself
        self.assertFalse(valid(now - timedelta(seconds=1)))
        self.assertTrue(valid(now + timedelta(seconds=1)))
        self.assertTrue(DoorCodeCreateSerializer(data=self._create_body(end_at=None), context={"now": now}).is_valid())

    def test_create_with_a_future_end_at_and_the_validity_field(self):
        gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.post(
                reverse("door-codes"), self._create_body(end_at=_iso(self._from_now(days=1))), format="json"
            )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["data"]["validity"], "valid")

    def test_update_rejects_a_past_end_at(self):
        code, gateway = self._temporary_code([self.BACK])

        response = self._patch(code, gateway, {"end_at": _iso(self._ago(minutes=1))})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("end_at", response.json()["error"]["details"])
        self.assertTrue(DoorCode.objects.get(id=code.id).end_at > timezone.now())

    def test_update_end_at_edges(self):
        code, _gateway = self._temporary_code([self.BACK])
        now = timezone.now()

        def valid(**body) -> bool:
            return DoorCodeUpdateSerializer(
                instance=code, data={**body, "reauth_password": "pass"}, partial=True, context={"now": now}
            ).is_valid()

        self.assertFalse(valid(end_at=_iso(now)))
        self.assertTrue(valid(end_at=_iso(now + timedelta(seconds=1))))
        self.assertTrue(valid(end_at=None))

    def test_an_unchanged_past_end_at_can_be_sent_back(self):
        code, gateway = self._expired_code()

        response = self._patch(code, gateway, {"end_at": _iso(code.end_at), "label": "Renamed"})

        self.assertEqual(response.status_code, 200, response.content)
        code.refresh_from_db()
        self.assertEqual(code.label, "Renamed")
        self.assertFalse(code.is_active)

    def test_moving_only_start_at_on_an_expired_code_sends_its_end_at_back(self):
        # The edit form sends both dates when either one changes.
        code, gateway = self._expired_code()
        new_start = code.end_at - timedelta(days=2)

        response = self._patch(code, gateway, {"start_at": _iso(new_start), "end_at": _iso(code.end_at)})

        self.assertEqual(response.status_code, 200, response.content)
        code.refresh_from_db()
        self.assertEqual(code.start_at, new_start)
        self.assertFalse(code.is_active)
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_a_changed_past_end_at_is_still_rejected_on_an_expired_code(self):
        code, gateway = self._expired_code()

        response = self._patch(code, gateway, {"end_at": _iso(code.end_at - timedelta(minutes=5))})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("end_at", response.json()["error"]["details"])

    def test_turning_on_with_the_unchanged_past_end_at_is_rejected(self):
        code, gateway = self._expired_code()

        response = self._patch(code, gateway, {"is_active": True, "end_at": _iso(code.end_at)})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("is_active", response.json()["error"]["details"])
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)

    def test_start_at_equal_to_end_at_is_rejected(self):
        at = _iso(self._from_now(days=1))

        response = self.client.post(reverse("door-codes"), self._create_body(start_at=at, end_at=at), format="json")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["error"]["details"]["end_at"], ["end_at must be after start_at."])
        self.assertFalse(DoorCode.objects.exists())

        code, gateway = self._temporary_code([self.BACK])
        response = self._patch(code, gateway, {"start_at": at, "end_at": at})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["error"]["details"]["end_at"], ["end_at must be after start_at."])

        response = self._patch(code, gateway, {"start_at": _iso(code.end_at)})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("end_at", response.json()["error"]["details"])

    def test_turning_on_an_expired_code_is_rejected(self):
        code, gateway = self._expired_code()

        response = self._patch(code, gateway, {"is_active": True})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("is_active", response.json()["error"]["details"])
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(gateway.invoke_calls, [])

    def test_turning_on_an_expired_code_with_end_at_exactly_now_is_rejected(self):
        code, _gateway = self._expired_code()
        now = timezone.now()
        code = self._move(code, end_at=now)

        serializer = DoorCodeUpdateSerializer(
            instance=code, data={"is_active": True, "reauth_password": "pass"}, partial=True, context={"now": now}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("is_active", serializer.errors)

    def test_extending_end_at_does_not_turn_an_expired_code_back_on(self):
        code, gateway = self._expired_code()

        response = self._patch(code, gateway, {"end_at": _iso(self._from_now(days=2))})

        self.assertEqual(response.status_code, 200, response.content)
        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(response.json()["data"]["validity"], "valid")

    def test_turning_on_with_a_later_end_at_in_the_same_save_pushes_it(self):
        code, gateway = self._expired_code()

        response = self._patch(code, gateway, {"is_active": True, "end_at": _iso(self._from_now(days=2))})

        self.assertEqual(response.status_code, 200, response.content)
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(self._calls(gateway, "set"), [(12, [1, 1, self.PIN])])
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_an_expired_code_that_is_still_on_can_be_turned_off(self):
        code, gateway = self._expired_code(is_active=True)

        response = self._patch(code, gateway, {"is_active": False})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._lock_codes(gateway, 12), {})

    def test_validity_field(self):
        now = timezone.now()
        hour = timedelta(hours=1)
        cases = {
            "valid": {},
            "scheduled": {"start_at": now + hour},
            "expired": {"end_at": now - hour},
            "exhausted": {"max_uses": 2, "uses_count": 2},
        }
        for expected, fields in cases.items():
            with self.subTest(expected):
                code = DoorCode.objects.create(
                    user=self.user,
                    encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
                    pin_length=len(self.PIN),
                    code_type=DoorCode.CodeType.TEMPORARY,
                    **fields,
                )
                data = DoorCodeSerializer(
                    DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id), context={"now": now}
                ).data
                self.assertEqual(data["validity"], expected)


class SyncedCodeValidityTests(_LifecycleTestBase, APITestCase):
    """A synced code the scheduler retired at its end_at can be turned back on (issue #145, N2)."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def _sync(self, gateway: FakeGateway) -> lock_config_sync_uc.SyncResult:
        return lock_config_sync_uc.sync_lock_config(
            lock_entity_id=self.BACK, target_user=self.user, actor_user=self.user, zwavejs=gateway
        )

    def _patch(self, code: DoorCode, gateway: FakeGateway, body: dict):
        url = reverse("door-code-detail", args=[code.id])
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            return self.client.patch(url, {**body, "reauth_password": "pass"}, format="json")

    def _synced_code(self) -> tuple[DoorCode, ClearFailingGateway]:
        """A dated code lock sync took over, the way the conversion leaves them: synced and permanent."""
        code, gateway = self._temporary_code([self.BACK])
        # Only syncs from before #166 converted manual codes, so the row is set up the way they left it.
        # A sync that read no schedule off the slot made it permanent and kept its dates.
        code = self._move(
            code, source=DoorCode.Source.SYNCED, code_type=DoorCode.CodeType.PERMANENT, label=code.label or "Slot 1"
        )
        self.assertIsNotNone(code.end_at)
        gateway.invoke_calls.clear()
        return code, gateway

    def _retired_synced_code(self) -> tuple[DoorCode, ClearFailingGateway]:
        code, gateway = self._synced_code()
        self._move(code, end_at=self._ago(minutes=5))
        self.assertEqual(self._enforce(gateway), 1)
        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})
        gateway.invoke_calls.clear()
        return code, gateway

    def test_a_retired_synced_code_is_turned_back_on_pushed_and_left_alone_by_lock_sync(self):
        code, gateway = self._retired_synced_code()
        # A sync while it's off and cleared doesn't touch it.
        self._sync(gateway)
        self.assertEqual(DoorCode.objects.count(), 1)
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)

        response = self._patch(
            code,
            gateway,
            {
                "is_active": True,
                "start_at": _iso(code.start_at) if code.start_at else None,
                "end_at": _iso(self._from_now(days=2)),
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(self._calls(gateway, "set"), [(12, [1, 1, self.PIN])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(response.json()["data"]["validity"], "valid")

        # Lock sync keeps it on, with its PIN and slot, and doesn't import a copy.
        gateway.invoke_calls.clear()
        result = self._sync(gateway)
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(code.source, DoorCode.Source.SYNCED)
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(lock_push_uc.decrypt_pin_or_none(code), self.PIN)
        self.assertEqual(DoorCode.objects.count(), 1)
        self.assertEqual(result.created, 0)
        self.assertEqual([s.action for s in result.slots], ["unchanged"])
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._enforce(gateway), 0)

    def test_moving_only_the_end_later_leaves_it_off_and_it_can_still_be_turned_on(self):
        code, gateway = self._retired_synced_code()

        response = self._patch(code, gateway, {"end_at": _iso(self._from_now(days=2))})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(self._calls(gateway, "set"), [])

        response = self._patch(code, gateway, {"is_active": True})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})

    def test_the_manual_rules_apply_to_a_retired_synced_code(self):
        code, gateway = self._retired_synced_code()

        response = self._patch(code, gateway, {"is_active": True})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("is_active", response.json()["error"]["details"])

        response = self._patch(code, gateway, {"end_at": _iso(code.end_at - timedelta(hours=1))})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("end_at", response.json()["error"]["details"])

        # Its unchanged end_at can come back, like the edit form sends it.
        response = self._patch(code, gateway, {"end_at": _iso(code.end_at), "label": "Guest"})
        self.assertEqual(response.status_code, 200, response.content)

        # The rest stays the lock's.
        for body in ({"code": "8642"}, {"days_of_week": 3}, {"lock_entity_ids": [self.SIDE]}):
            with self.subTest(body=body):
                response = self._patch(code, gateway, body)
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_an_active_synced_code_or_one_without_an_end_at_stays_read_only(self):
        active, gateway = self._synced_code()
        for body in ({"is_active": False}, {"end_at": _iso(self._from_now(days=5))}):
            with self.subTest(code="active", body=body):
                response = self._patch(active, gateway, body)
                self.assertEqual(response.status_code, 400, response.content)

        undated = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            encrypted_pin=SettingsEncryption.get().encrypt("9753"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=False,
        )
        for body in ({"is_active": True}, {"end_at": _iso(self._from_now(days=5))}):
            with self.subTest(code="undated", body=body):
                response = self._patch(undated, gateway, body)
                self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(DoorCode.objects.get(id=undated.id).is_active)


class DateComparisonTests(_LifecycleTestBase, APITestCase):
    """The update serializer compares dates the way the edit form sends them back."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def _patch(self, code: DoorCode, gateway: FakeGateway, body: dict):
        url = reverse("door-code-detail", args=[code.id])
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            return self.client.patch(url, {**body, "reauth_password": "pass"}, format="json")

    def test_a_past_end_at_with_seconds_sent_back_without_them_is_unchanged(self):
        code, gateway = self._temporary_code([self.BACK])
        stored = (self._ago(days=1)).replace(second=37, microsecond=123456)
        code = self._move(code, end_at=stored)
        door_codes_uc.retire_door_code(code=code, reason="expired", zwavejs=gateway)

        form_value = stored.replace(second=0, microsecond=0)
        response = self._patch(
            code, gateway, {"start_at": _iso(stored - timedelta(days=3)), "end_at": _iso(form_value)}
        )

        self.assertEqual(response.status_code, 200, response.content)
        code.refresh_from_db()
        # Treated as unchanged, so the stored value keeps its seconds.
        self.assertEqual(code.end_at, stored)

        # A different minute is a change, and a past one is refused.
        response = self._patch(code, gateway, {"end_at": _iso(form_value - timedelta(minutes=1))})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("end_at", response.json()["error"]["details"])

    def test_an_unrelated_edit_on_a_row_with_equal_dates_is_allowed(self):
        code, gateway = self._temporary_code([self.BACK])
        at = self._from_now(days=1)
        code = self._move(code, start_at=at, end_at=at)

        response = self._patch(code, gateway, {"days_of_week": 0b0011111})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(DoorCode.objects.get(id=code.id).days_of_week, 0b0011111)

        # Changing a date still checks them.
        response = self._patch(code, gateway, {"start_at": _iso(at + timedelta(hours=1))})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("end_at", response.json()["error"]["details"])
