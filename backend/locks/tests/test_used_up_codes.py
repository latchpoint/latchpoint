"""Issue #145 part 2b: a used up door code comes off its locks (ADR-0109, ADR-0114).

A code is used up when its ``uses_count`` reaches its ``max_uses`` (or a one-time
code has been used). Keypad uses are counted by ``locks.use_cases.code_usage``.
Imports of what this change adds stay inside the tests, so on a branch without
it each test fails on its own instead of the whole module failing to import.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.db.models import F
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from alarm.crypto import SettingsEncryption
from locks.keypad_events import KeypadUnlock
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_door_code_lifecycle import _iso, _LifecycleTestBase
from locks.tests.test_door_code_locking import _OtherHolder, _when_waiting_on
from locks.tests.test_lock_push import ClearFailingGateway, FakeGateway
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.code_usage import UseOutcome, handle_keypad_unlock
from locks.use_cases.lock_push import PushSuperseded

NODES = {"lock.back_door": 12, "lock.side_door": 13}


class ExhaustedPredicateTests(SimpleTestCase):
    def test_a_used_up_code_does_not_belong_on_a_lock(self):
        from locks.use_cases.code_lifecycle import belongs_on_lock

        self.assertTrue(belongs_on_lock(DoorCode(code_type=DoorCode.CodeType.PERMANENT, max_uses=2, uses_count=1)))
        self.assertFalse(belongs_on_lock(DoorCode(code_type=DoorCode.CodeType.PERMANENT, max_uses=2, uses_count=2)))


class _UsedUpTestBase(_LifecycleTestBase):
    def _code(self, lock_entity_ids: list[str], **kwargs) -> tuple[DoorCode, ClearFailingGateway]:
        kwargs.setdefault("code_type", DoorCode.CodeType.PERMANENT)
        return self._pushed_code(lock_entity_ids, **kwargs)

    def _use(self, lock_entity_id: str, slot: int, *, at) -> UseOutcome:
        """A keypad unlock on the lock, run through the commit so its wake goes out."""
        with self.captureOnCommitCallbacks(execute=True):
            return handle_keypad_unlock(
                KeypadUnlock(node_id=NODES[lock_entity_id], slot=slot, event=6), home_id=None, now=at
            )

    def _used_up_off(self, lock_entity_ids: list[str], **kwargs) -> tuple[DoorCode, ClearFailingGateway]:
        """A code with max_uses 2 used twice and retired."""
        code, gateway = self._code(lock_entity_ids, max_uses=2, **kwargs)
        self._move(code, uses_count=2)
        self.assertEqual(self._enforce(gateway), 1)
        code.refresh_from_db()
        self.assertFalse(code.is_active)
        gateway.invoke_calls.clear()
        return code, gateway


class RetireUsedUpTests(_UsedUpTestBase):
    def test_the_filter_matches_the_predicate(self):
        from locks.use_cases.code_lifecycle import exhausted_q, is_exhausted

        cases = [
            (DoorCode.CodeType.PERMANENT, None, 10, False),
            (DoorCode.CodeType.PERMANENT, 3, 2, False),
            (DoorCode.CodeType.PERMANENT, 3, 3, True),
            (DoorCode.CodeType.PERMANENT, 3, 4, True),
            (DoorCode.CodeType.ONE_TIME, None, 0, False),
            (DoorCode.CodeType.ONE_TIME, None, 1, True),
            (DoorCode.CodeType.ONE_TIME, 2, 1, False),
        ]
        for code_type, max_uses, uses_count, expected in cases:
            with self.subTest(code_type=code_type, max_uses=max_uses, uses_count=uses_count):
                code = DoorCode.objects.create(
                    user=self.user,
                    encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
                    pin_length=len(self.PIN),
                    code_type=code_type,
                    max_uses=max_uses,
                    uses_count=uses_count,
                )
                self.assertEqual(is_exhausted(code), expected)
                self.assertEqual(DoorCode.objects.filter(id=code.id).filter(exhausted_q()).exists(), expected)

    def test_two_keypad_uses_retire_a_max_uses_2_code_and_clear_every_lock(self):
        code, gateway = self._code([self.BACK, self.SIDE], max_uses=2)
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        now = timezone.now()

        with patch("scheduler.runner.wake_task") as wake:
            self.assertEqual(self._use(self.BACK, 1, at=now - timedelta(seconds=40)), UseOutcome.COUNTED)
            # One use left: nothing to wake and the scheduler leaves it on.
            wake.assert_not_called()
            self.assertEqual(self._enforce(gateway), 0)
            self.assertTrue(DoorCode.objects.get(id=code.id).is_active)

            # The second use on the other lock counts toward the same total.
            self.assertEqual(self._use(self.SIDE, 1, at=now - timedelta(seconds=20)), UseOutcome.COUNTED)
            wake.assert_called_once_with("enforce_door_code_validity")

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 2)
        self.assertTrue(code.is_active)
        self.assertEqual(self._enforce(gateway), 1)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(code.uses_count, 2)
        self.assertCountEqual(self._calls(gateway, "clear"), [(12, [1]), (13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: None})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        event = self._updated_event(code)
        self.assertEqual(event.metadata["updated_fields"], ["is_active"])
        self.assertEqual(event.metadata["reason"], "exhausted")
        self.assertIsNone(event.user)

        # Retired once: the next tick leaves it alone.
        gateway.invoke_calls.clear()
        self.assertEqual(self._enforce(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

    def test_the_dedupe_window_does_not_double_count(self):
        code, gateway = self._code([self.BACK], max_uses=2)
        now = timezone.now()

        with patch("scheduler.runner.wake_task") as wake:
            self.assertEqual(self._use(self.BACK, 1, at=now - timedelta(seconds=5)), UseOutcome.COUNTED)
            # The lock reporting the same unlock again.
            self.assertEqual(self._use(self.BACK, 1, at=now), UseOutcome.DUPLICATE)
            wake.assert_not_called()

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 1)
        self.assertEqual(self._enforce(gateway), 0)
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})

    def test_a_one_time_code_is_retired_after_one_use(self):
        code, gateway = self._code([self.BACK], code_type=DoorCode.CodeType.ONE_TIME)

        self.assertEqual(self._use(self.BACK, 1, at=timezone.now()), UseOutcome.COUNTED)
        self.assertEqual(self._enforce(gateway), 1)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._updated_event(code).metadata["reason"], "exhausted")

    def test_a_code_without_max_uses_is_never_retired_for_uses(self):
        code, gateway = self._code([self.BACK])
        self._move(code, uses_count=500)

        self.assertEqual(self._enforce(gateway), 0)
        self.assertTrue(DoorCode.objects.get(id=code.id).is_active)

    def test_a_code_both_expired_and_used_up_is_retired_once_as_expired(self):
        code, gateway = self._code([self.BACK], code_type=DoorCode.CodeType.TEMPORARY, max_uses=1)
        self._move(code, uses_count=1, end_at=self._ago(minutes=1))

        self.assertEqual(self._enforce(gateway), 1)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        reasons = list(
            DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_UPDATED)
            .exclude(metadata__reason=None)
            .values_list("metadata__reason", flat=True)
        )
        self.assertEqual(reasons, ["expired"])

    def test_the_retire_checks_again_by_its_reason(self):
        code, gateway = self._code([self.BACK], max_uses=2)

        # Not used up yet, so an exhausted retire leaves it alone.
        self.assertIsNone(door_codes_uc.retire_door_code(code=code, reason="exhausted", zwavejs=gateway))
        # Used up but not expired, so an expired retire leaves it alone too.
        code = self._move(code, uses_count=2)
        self.assertIsNone(door_codes_uc.retire_door_code(code=code, reason="expired", zwavejs=gateway))
        self.assertTrue(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(gateway.invoke_calls, [])
        with self.assertRaises(ValueError):
            door_codes_uc.retire_door_code(code=code, reason="tired", zwavejs=gateway)

        self.assertIsNotNone(door_codes_uc.retire_door_code(code=code, reason="exhausted", zwavejs=gateway))
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)

    def test_max_uses_raised_while_waiting_for_the_lock_means_no_retire(self):
        code, gateway = self._code([self.BACK], max_uses=2)
        stale = self._move(code, uses_count=2)
        holder = _OtherHolder(self.BACK).acquire()
        self.addCleanup(holder.release)

        def raise_then_let_go():
            # A save that was holding the lock raised max_uses.
            DoorCode.objects.filter(id=code.id).update(max_uses=5)
            holder.release()

        with _when_waiting_on(self.BACK, raise_then_let_go) as fired:
            result = door_codes_uc.retire_door_code(code=stale, reason="exhausted", zwavejs=gateway)

        self.assertEqual(fired, [f"lock_sync:{self.BACK}"])
        self.assertIsNone(result)
        self.assertTrue(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})

    def test_a_use_landing_during_the_retire_is_kept(self):
        # The retire is a locked update, which must not write back the count it read.
        code, gateway = self._code([self.BACK], max_uses=2)
        code = self._move(code, uses_count=2)
        used_at = timezone.now()
        real_refuse = door_codes_uc._refuse_lock_changes_leaving_no_locks

        def use_lands_now(*, code, changes):
            DoorCode.objects.filter(id=code.id).update(
                uses_count=F("uses_count") + 1, last_used_at=used_at, last_used_lock=self.SIDE
            )
            return real_refuse(code=code, changes=changes)

        with patch.object(door_codes_uc, "_refuse_lock_changes_leaving_no_locks", use_lands_now):
            retired = door_codes_uc.retire_door_code(code=code, reason="exhausted", zwavejs=gateway)

        fresh = DoorCode.objects.get(id=code.id)
        self.assertFalse(fresh.is_active)
        self.assertEqual((fresh.uses_count, fresh.last_used_at, fresh.last_used_lock), (3, used_at, self.SIDE))
        self.assertEqual(retired.uses_count, 3)

    def test_a_busy_lock_does_not_raise_and_the_next_tick_retires_it(self):
        code, gateway = self._code([self.BACK], max_uses=1)
        self._move(code, uses_count=1)
        holder = _OtherHolder(self.BACK).acquire()
        self.addCleanup(holder.release)

        from locks.use_cases import lock_config_sync as lock_config_sync_uc

        with patch.object(lock_config_sync_uc, "SYNC_LOCK_WAIT_SECONDS", 0.05):
            self.assertEqual(self._enforce(gateway), 0)
        self.assertTrue(DoorCode.objects.get(id=code.id).is_active)

        holder.release()
        self.assertEqual(self._enforce(gateway), 1)
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)

    def test_a_failed_clear_goes_pending_and_the_retry_task_finishes_it(self):
        code, gateway = self._code([self.BACK], max_uses=1)
        self._move(code, uses_count=1)
        gateway.clear_fails_on = {12}

        self.assertEqual(self._enforce(gateway), 1)
        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})

        gateway.clear_fails_on = set()
        self._push_pending(gateway)
        code.refresh_from_db()
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(self._calls(gateway, "set"), [])


class RetryUsedUpTests(_UsedUpTestBase):
    def test_retry_on_a_used_up_code_that_is_still_on_retires_it(self):
        code, gateway = self._code([self.BACK, self.SIDE], max_uses=2)
        # The push gave up, and it got used up before the scheduler turned it off.
        DoorCode.objects.filter(id=code.id).update(
            push_state=DoorCode.PushState.FAILED, push_attempt_count=5, last_push_error="gave up"
        )
        code = self._move(code, uses_count=2)

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._updated_event(code).metadata["reason"], "exhausted")
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_retry_on_a_retired_used_up_code_is_refused(self):
        code, gateway = self._used_up_off([self.BACK])

        with self.assertRaises(door_codes_uc.DoorCodeInactive):
            door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)
        self.assertEqual(gateway.invoke_calls, [])


class PushGateTests(_UsedUpTestBase):
    """Nothing pushes a used up code, even while it's still on (issue #145)."""

    def _used_up_waiting_for_a_push(self) -> DoorCode:
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.PERMANENT,
            max_uses=2,
            lock_entity_ids=[self.BACK],
            actor_user=self.user,
        )
        DoorCodeLockAssignment.objects.filter(door_code=code).update(push_requested_at=timezone.now())
        return self._move(code, uses_count=2)

    def test_the_retry_task_does_not_push_it(self):
        self._used_up_waiting_for_a_push()
        gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)

        self._push_pending(gateway)

        self.assertEqual(self._calls(gateway, "set"), [])

    def test_a_direct_push_skips_it(self):
        code = self._used_up_waiting_for_a_push()
        gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)

        stale = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
        self.assertEqual(lock_push_uc.push_door_code_to_assigned_locks(door_code=stale, zwavejs=gateway), ([], []))
        with self.assertRaises(PushSuperseded):
            lock_push_uc.push_door_code_to_lock(door_code=stale, lock_entity_id=self.BACK, zwavejs=gateway)
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_a_push_that_loaded_it_before_its_last_use_is_superseded(self):
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.PERMANENT,
            max_uses=2,
            lock_entity_ids=[self.BACK],
            actor_user=self.user,
        )
        stale = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
        self._move(code, uses_count=2)
        gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)

        with self.assertRaises(PushSuperseded):
            lock_push_uc.push_door_code_to_lock(door_code=stale, lock_entity_id=self.BACK, zwavejs=gateway)
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_it_is_not_queued_or_reconciled(self):
        from locks.use_cases.added_lock_reconcile import reconcile_due

        code = self._used_up_waiting_for_a_push()
        DoorCodeLockAssignment.objects.filter(door_code=code).update(reconcile_requested_at=timezone.now())
        now = timezone.now()

        self.assertFalse(lock_push_uc.queued_push_assignments(now=now, max_attempts=24).exists())
        self.assertFalse(reconcile_due(now=now, max_attempts=24, fresh_only=False).exists())
        # Raising max_uses puts it back in both.
        DoorCode.objects.filter(id=code.id).update(max_uses=3)
        self.assertTrue(reconcile_due(now=now, max_attempts=24, fresh_only=False).exists())

    def test_the_start_pass_does_not_push_it(self):
        code = self._used_up_waiting_for_a_push()
        DoorCode.objects.filter(id=code.id).update(start_at=self._ago(minutes=1), is_active=True)
        gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)

        self._enforce(gateway)

        self.assertEqual(self._calls(gateway, "set"), [])
        # Retired instead, and it had nothing on the lock.
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)


class ReEnableTests(_UsedUpTestBase, APITestCase):
    """A used up code comes back once max_uses is raised and Active is turned on (issue #145)."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def _patch(self, code: DoorCode, gateway: FakeGateway, body: dict):
        url = reverse("door-code-detail", args=[code.id])
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            return self.client.patch(url, {**body, "reauth_password": "pass"}, format="json")

    def test_turning_on_a_used_up_code_is_refused(self):
        code, gateway = self._used_up_off([self.BACK])

        response = self._patch(code, gateway, {"is_active": True})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            response.json()["error"]["details"]["is_active"],
            ["This code is used up. Raise max_uses above its uses to turn it back on."],
        )
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(gateway.invoke_calls, [])

    def test_max_uses_at_the_count_is_still_used_up(self):
        code, gateway = self._used_up_off([self.BACK])

        response = self._patch(code, gateway, {"is_active": True, "max_uses": 2})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("is_active", response.json()["error"]["details"])

    def test_raising_max_uses_then_turning_it_on_pushes_it_again(self):
        code, gateway = self._used_up_off([self.BACK, self.SIDE])

        response = self._patch(code, gateway, {"max_uses": 4})
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        # Raising it alone doesn't turn it back on.
        self.assertFalse(data["is_active"])
        self.assertEqual(data["validity"], "valid")
        self.assertEqual(self._calls(gateway, "set"), [])

        response = self._patch(code, gateway, {"is_active": True})
        self.assertEqual(response.status_code, 200, response.content)
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual((code.max_uses, code.uses_count), (4, 2))
        self.assertCountEqual(self._calls(gateway, "set"), [(12, [1, 1, self.PIN]), (13, [1, 1, self.PIN])])
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        # And the scheduler leaves it on.
        self.assertEqual(self._enforce(gateway), 0)
        self.assertTrue(DoorCode.objects.get(id=code.id).is_active)

    def test_raising_max_uses_and_turning_it_on_in_one_save(self):
        code, gateway = self._used_up_off([self.BACK])

        response = self._patch(code, gateway, {"is_active": True, "max_uses": 3})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(self._calls(gateway, "set"), [(12, [1, 1, self.PIN])])

    def test_clearing_max_uses_and_turning_it_on(self):
        code, gateway = self._used_up_off([self.BACK])

        response = self._patch(code, gateway, {"is_active": True, "max_uses": None})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(DoorCode.objects.get(id=code.id).is_active)

    def test_a_used_one_time_code_comes_back_with_a_max_uses(self):
        code, gateway = self._code([self.BACK], code_type=DoorCode.CodeType.ONE_TIME)
        self._move(code, uses_count=1)
        self._enforce(gateway)

        response = self._patch(code, gateway, {"is_active": True})
        self.assertEqual(response.status_code, 400, response.content)

        response = self._patch(code, gateway, {"is_active": True, "max_uses": 2})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(DoorCode.objects.get(id=code.id).is_active)

    def test_lowering_max_uses_to_the_count_retires_it(self):
        code, gateway = self._code([self.BACK, self.SIDE], max_uses=5)
        self._move(code, uses_count=2)

        response = self._patch(code, gateway, {"max_uses": 2})

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertFalse(data["is_active"])
        self.assertEqual(data["validity"], "exhausted")
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: None})
        self.assertEqual(self._updated_event(code).metadata["reason"], "exhausted")

    def test_lowering_max_uses_below_the_count_retires_it(self):
        code, gateway = self._code([self.BACK], max_uses=5)
        self._move(code, uses_count=3)

        response = self._patch(code, gateway, {"max_uses": 1, "label": "Cleaner"})

        self.assertEqual(response.status_code, 200, response.content)
        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(code.label, "Cleaner")
        self.assertEqual(self._lock_codes(gateway, 12), {})

    def test_lowering_max_uses_above_the_count_leaves_it_on(self):
        code, gateway = self._code([self.BACK], max_uses=5)
        self._move(code, uses_count=2)

        response = self._patch(code, gateway, {"max_uses": 3})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})

    def test_a_retire_that_fails_after_lowering_is_left_to_the_scheduler(self):
        code, gateway = self._code([self.BACK], max_uses=5)
        self._move(code, uses_count=2)

        with patch.object(door_codes_uc, "retire_door_code", side_effect=RuntimeError("busy")):
            response = self._patch(code, gateway, {"max_uses": 2})

        self.assertEqual(response.status_code, 200, response.content)
        code.refresh_from_db()
        self.assertEqual(code.max_uses, 2)
        self.assertTrue(code.is_active)

        self.assertEqual(self._enforce(gateway), 1)
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})


class SyncedUsedUpTests(_UsedUpTestBase, APITestCase):
    """Synced codes can't set max_uses (ADR-0082), but one from before #166 may have one."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def test_a_synced_code_with_max_uses_is_retired_off_every_lock(self):
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True)
        gateway._lock_codes[(12, 3)] = self.PIN
        gateway._lock_codes[(13, 2)] = self.PIN
        code = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            max_uses=1,
            uses_count=1,
            push_state=DoorCode.PushState.PUSHED,
        )
        # Imported from the back door, with the side door added in latchpoint.
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK, slot_index=3)
        DoorCodeLockAssignment.objects.create(
            door_code=code, lock_entity_id=self.SIDE, slot_index=2, last_push_attempt_at=timezone.now()
        )

        self.assertEqual(self._enforce(gateway), 1)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertCountEqual(self._calls(gateway, "clear"), [(12, [3]), (13, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})

        # Its max_uses and Active are the lock's, so it stays off from here.
        url = reverse("door-code-detail", args=[code.id])
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.patch(
                url, {"is_active": True, "max_uses": 5, "reauth_password": "pass"}, format="json"
            )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(DoorCode.objects.get(id=code.id).is_active)

    def test_a_dated_synced_code_that_is_used_up_cannot_be_turned_on(self):
        code = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=False,
            max_uses=1,
            uses_count=1,
            end_at=self._from_now(days=1),
            push_state=DoorCode.PushState.PUSHED,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK)

        url = reverse("door-code-detail", args=[code.id])
        response = self.client.patch(
            url, {"is_active": True, "end_at": _iso(code.end_at), "reauth_password": "pass"}, format="json"
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("is_active", response.json()["error"]["details"])
