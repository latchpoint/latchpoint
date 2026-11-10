"""A synced code's locks can be added and removed like a manual code's (ADR 0082).

The real case: the master code was imported from the Front Door by lock sync,
so it's ``source=synced``, and the Back Door has to be added to it. Latchpoint
pushes its PIN to an added lock and clears it off a removed one, while the PIN,
schedule and max uses stay the lock's.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from integrations_zwavejs.manager import ZwavejsCommandError
from rest_framework.test import APITestCase

from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_lock_push import ClearFailingGateway
from locks.tests.test_tracking_integrity import _TrackingTestBase
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_config_sync as lock_config_sync_uc
from locks.use_cases import lock_push as lock_push_uc

# Node ids the base class gives the locks.
NODE = {"lock.back_door": 12, "lock.side_door": 13, "lock.front_door": 14}
OTHER_PIN = "9999"
PIN_UNKNOWN = (
    "Latchpoint doesn't have a readable PIN for this code, so it can't put it on another lock. "
    "Either the lock it was synced from hides its codes or the stored PIN can't be decrypted."
)


class _SyncedLocksTestBase(_TrackingTestBase, APITestCase):
    # Whether a set reaches the Z-Wave JS value cache right away. The Stale*
    # subclasses run the same tests with the FakeGateway default, where it
    # doesn't, ie the cache still calls a pushed slot Available.
    CACHE_UPDATES_ON_SET = True

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def _gateway(self, **kwargs) -> ClearFailingGateway:
        """Front Door slot 1 holds the master PIN, Back Door slot 1 holds someone else's code."""
        kwargs.setdefault("cache_updates_on_set", self.CACHE_UPDATES_ON_SET)
        gateway = ClearFailingGateway(usersNumber=5, **kwargs)
        for key, pin in (((14, 1), self.PIN), ((12, 1), OTHER_PIN)):
            gateway._lock_codes[key] = pin
            gateway._cache_codes[key] = pin
        return gateway

    def _sync(self, gateway: ClearFailingGateway, lock_entity_id: str) -> lock_config_sync_uc.SyncResult:
        return lock_config_sync_uc.sync_lock_config(
            lock_entity_id=lock_entity_id, target_user=self.user, actor_user=self.user, zwavejs=gateway
        )

    def _master(self, gateway: ClearFailingGateway) -> DoorCode:
        """The master code, imported from the Front Door the way lock sync does it.

        The Back Door is synced too, so the other code in its slot 1 has a row.
        """
        self._sync(gateway, self.BACK)
        self._sync(gateway, self.FRONT)
        master = DoorCode.objects.get(lock_assignments__lock_entity_id=self.FRONT)
        self.assertEqual(master.source, DoorCode.Source.SYNCED)
        self.assertEqual(self._slots(master), {self.FRONT: 1})
        DoorCode.objects.filter(id=master.id).update(label="Master")
        gateway.invoke_calls.clear()
        return DoorCode.objects.get(id=master.id)

    def _patch_response(self, code: DoorCode, gateway: ClearFailingGateway, body: dict):
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            return self.client.patch(
                reverse("door-code-detail", args=[code.id]), {**body, "reauth_password": "pass"}, format="json"
            )

    def _patch(self, code: DoorCode, gateway: ClearFailingGateway, body: dict) -> dict:
        response = self._patch_response(code, gateway, body)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]

    def _master_on_both(self) -> tuple[DoorCode, ClearFailingGateway]:
        gateway = self._gateway()
        master = self._master(gateway)
        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        gateway.invoke_calls.clear()
        return DoorCode.objects.get(id=master.id), gateway

    @staticmethod
    def _slot_row(result: lock_config_sync_uc.SyncResult, slot_index: int) -> lock_config_sync_uc.SlotSyncResult:
        return next(row for row in result.slots if row.slot_index == slot_index)


class AddLockTests(_SyncedLocksTestBase):
    def test_adding_the_back_door_pushes_the_pin_into_a_free_slot_and_lock_sync_leaves_it_alone(self):
        gateway = self._gateway()
        master = self._master(gateway)
        other = DoorCode.objects.exclude(id=master.id).count()

        data = self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})

        # Slot 1 on the Back Door is someone else's, so the PIN goes in slot 2.
        self.assertEqual(self._calls(gateway, "set"), [(12, [2, 1, self.PIN])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._lock_codes(gateway, 14), {1: self.PIN})
        self.assertEqual(data["lock_entity_ids"], [self.BACK, self.FRONT])
        master.refresh_from_db()
        self.assertEqual(master.source, DoorCode.Source.SYNCED)
        self.assertEqual(master.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        back = DoorCodeLockAssignment.objects.get(door_code=master, lock_entity_id=self.BACK)
        self.assertEqual(back.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(self._updated_event(master).metadata["added_lock_entity_ids"], [self.BACK])
        # Nothing left for the #180 check or the scheduler.
        self.assertEqual(lock_push_uc.synced_attempt_slots_to_check(door_code=master), [])
        gateway.invoke_calls.clear()
        self._push_pending(gateway)
        self.assertEqual(gateway.invoke_calls, [])

        # A later sync of the Back Door finds slot 2 tracked by the master code.
        result = self._sync(gateway, self.BACK)

        row = self._slot_row(result, 2)
        self.assertEqual(row.door_code_id, master.id)
        self.assertNotEqual(row.action, "created")
        self.assertNotIn("duplicate_pin", row.warnings)
        self.assertEqual(row.duplicate_pin_door_code_ids, [])
        self.assertEqual(result.created, 0)
        self.assertEqual(DoorCode.objects.exclude(id=master.id).count(), other)
        self.assertFalse(DoorCode.objects.filter(label="Slot 2").exists())
        # And a sync of the Front Door doesn't see the Back Door's slot as a duplicate either.
        row = self._slot_row(self._sync(gateway, self.FRONT), 1)
        self.assertEqual((row.door_code_id, row.duplicate_pin_door_code_ids), (master.id, []))
        master.refresh_from_db()
        self.assertTrue(master.is_active)
        self.assertEqual(master.source, DoorCode.Source.SYNCED)
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_an_unconfirmed_push_to_the_added_lock_is_adopted_and_never_imported(self):
        # Every readback on the Back Door times out, so the slot is only on record as an attempt.
        gateway = self._gateway(get_responses={12: [ZwavejsCommandError("driver TimeoutError after 5.0s")] * 3})
        master = self._master(gateway)

        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: None})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=master), [self.BACK])

        # A sync meanwhile leaves the slot to the master code's own retry. With a
        # stale cache it doesn't even see the slot as occupied.
        result = self._sync(gateway, self.BACK)
        rows = [(row.action, row.door_code_id) for row in result.slots if row.slot_index == 2]
        self.assertEqual(rows, [("skipped", master.id)] if self.CACHE_UPDATES_ON_SET else [])
        self.assertEqual(result.created, 0)

        # The scheduler's retry adopts the slot instead of writing a second copy.
        gateway.invoke_calls.clear()
        self._push_pending(gateway)
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=master), [])

        result = self._sync(gateway, self.BACK)
        self.assertEqual(self._slot_row(result, 2).door_code_id, master.id)
        self.assertEqual(result.created, 0)
        self.assertEqual(DoorCode.objects.get(id=master.id).source, DoorCode.Source.SYNCED)

    def test_a_full_lock_list_works_too_but_not_an_empty_one(self):
        gateway = self._gateway()
        master = self._master(gateway)

        self._patch(master, gateway, {"lock_entity_ids": [self.FRONT, self.BACK]})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})

        # The door codes list leaves out a synced code with no locks.
        response = self._patch_response(master, gateway, {"lock_entity_ids": []})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("no locks", response.json()["error"]["message"])
        response = self._patch_response(master, gateway, {"remove_lock_entity_ids": [self.FRONT, self.BACK]})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})

    def test_a_lock_that_already_has_the_pin_as_another_code_is_refused_with_a_409(self):
        # Issue #188: the master PIN was typed in at the Back Door too, and a sync imported it.
        gateway = self._gateway()
        gateway._lock_codes[(12, 3)] = self.PIN
        gateway._cache_codes[(12, 3)] = self.PIN
        master = self._master(gateway)
        self._sync(gateway, self.BACK)
        copy = DoorCode.objects.get(lock_assignments__lock_entity_id=self.BACK, lock_assignments__slot_index=3)
        gateway.invoke_calls.clear()

        response = self._patch_response(master, gateway, {"add_lock_entity_ids": [self.BACK]})

        self.assertEqual(response.status_code, 409, response.content)
        message = response.json()["error"]["message"]
        self.assertIn(f'{self.BACK} already has this PIN in slot 3 as door code {copy.id} ("Slot 3")', message)
        self.assertIn("before adding that lock", message)
        self.assertNotIn(self.PIN, message)
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._slots(master), {self.FRONT: 1})

    def test_a_manual_code_gets_the_same_409_on_an_added_lock(self):
        gateway = self._gateway()
        copy = self._code(pin=self.PIN, source=DoorCode.Source.SYNCED, slots={self.BACK: 3}, label="Slot 3")
        code = door_codes_uc.create_door_code(
            user=self.user, raw_code=self.PIN, lock_entity_ids=[self.SIDE], actor_user=self.user, zwavejs=gateway
        )
        gateway.invoke_calls.clear()

        response = self._patch_response(code, gateway, {"add_lock_entity_ids": [self.BACK]})

        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn(f"as door code {copy.id}", response.json()["error"]["message"])
        self.assertIn("give this one a different PIN", response.json()["error"]["message"])
        self.assertEqual(gateway.invoke_calls, [])

    def test_an_off_synced_code_is_still_refused_but_an_off_manual_code_is_not(self):
        # An undated synced code only comes back on through lock sync, which never
        # runs the #188 check, so it's checked when the lock is added.
        gateway = self._gateway()
        master = self._master(gateway)
        copy = self._code(pin=self.PIN, source=DoorCode.Source.SYNCED, slots={self.BACK: 3}, label="Slot 3")
        DoorCode.objects.filter(id=master.id).update(is_active=False)

        response = self._patch_response(master, gateway, {"add_lock_entity_ids": [self.BACK]})

        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn(f"as door code {copy.id}", response.json()["error"]["message"])
        self.assertEqual(self._slots(master), {self.FRONT: 1})

        # A manual code is checked when it's turned on, with every lock it's on then.
        manual = self._code(pin=self.PIN, is_active=False, slots={self.SIDE: None})
        self._patch(manual, gateway, {"add_lock_entity_ids": [self.BACK]})
        self.assertEqual(self._slots(manual), {self.SIDE: None, self.BACK: None})
        response = self._patch_response(manual, gateway, {"is_active": True})
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_only_the_added_locks_are_checked(self):
        # A copy of the master PIN on the Front Door itself (lock sync flags it)
        # doesn't stop the Back Door from being added.
        gateway = self._gateway()
        master = self._master(gateway)
        self._code(pin=self.PIN, source=DoorCode.Source.SYNCED, slots={self.FRONT: 3}, label="Slot 3")

        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})

        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})


class UnknownPinTests(_SyncedLocksTestBase):
    def _masked_master(self) -> tuple[DoorCode, ClearFailingGateway]:
        """Imported from a Front Door that masks its codes, so latchpoint has no PIN."""
        gateway = self._gateway()
        gateway._cache_codes[(14, 1)] = "****"
        master = self._master(gateway)
        self.assertIsNone(master.encrypted_pin)
        return master, gateway

    def test_adding_a_lock_is_refused_with_a_400(self):
        master, gateway = self._masked_master()

        for body in ({"add_lock_entity_ids": [self.BACK]}, {"lock_entity_ids": [self.FRONT, self.BACK]}):
            with self.subTest(body=body):
                response = self._patch_response(master, gateway, body)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(response.json()["error"]["message"], PIN_UNKNOWN)
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._slots(master), {self.FRONT: 1})

    def test_a_stored_pin_that_cant_be_decrypted_counts_the_same(self):
        gateway = self._gateway()
        master = self._master(gateway)
        DoorCode.objects.filter(id=master.id).update(encrypted_pin="not-a-token")

        response = self._patch_response(master, gateway, {"add_lock_entity_ids": [self.BACK]})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["error"]["message"], PIN_UNKNOWN)

    def test_removing_a_lock_still_works(self):
        master, gateway = self._masked_master()
        DoorCodeLockAssignment.objects.create(
            door_code=master, lock_entity_id=self.BACK, slot_index=4, push_state=DoorCode.PushState.PUSHED
        )
        gateway._lock_codes[(12, 4)] = self.PIN

        data = self._patch(master, gateway, {"remove_lock_entity_ids": [self.BACK]})

        self.assertEqual(data["lock_entity_ids"], [self.FRONT])
        self.assertEqual(self._calls(gateway, "clear"), [(12, [4])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})


class RemoveLockTests(_SyncedLocksTestBase):
    def test_removing_the_added_lock_clears_its_slot(self):
        master, gateway = self._master_on_both()

        data = self._patch(master, gateway, {"remove_lock_entity_ids": [self.BACK]})

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(self._lock_codes(gateway, 14), {1: self.PIN})
        self.assertEqual(data["lock_entity_ids"], [self.FRONT])
        self.assertEqual(self._slots(master), {self.FRONT: 1})
        master.refresh_from_db()
        self.assertEqual((master.source, master.is_active), (DoorCode.Source.SYNCED, True))

    def test_removing_the_lock_it_was_imported_from_clears_that_slot(self):
        master, gateway = self._master_on_both()

        data = self._patch(master, gateway, {"remove_lock_entity_ids": [self.FRONT]})

        self.assertEqual(self._calls(gateway, "clear"), [(14, [1])])
        self.assertEqual(self._lock_codes(gateway, 14), {})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(data["lock_entity_ids"], [self.BACK])
        self.assertEqual(self._slots(master), {self.BACK: 2})
        master.refresh_from_db()
        self.assertEqual((master.source, master.is_active), (DoorCode.Source.SYNCED, True))

        # A Front Door sync finds nothing of it, and the Back Door still tracks it.
        self.assertEqual(self._sync(gateway, self.FRONT).created, 0)
        self.assertEqual(self._slot_row(self._sync(gateway, self.BACK), 2).door_code_id, master.id)

    def test_a_removal_whose_clear_fails_is_pending_and_retried_like_a_manual_codes(self):
        master, gateway = self._master_on_both()
        gateway.clear_fails_on = {12}

        data = self._patch(master, gateway, {"remove_lock_entity_ids": [self.BACK]})

        self.assertEqual(data["lock_entity_ids"], [self.FRONT])
        removing = {a["lock_entity_id"]: a["pending_removal"] for a in data["lock_slot_assignments"]}
        self.assertEqual(removing, {self.FRONT: False, self.BACK: True})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

        gateway.clear_fails_on = set()
        self._push_pending(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1})


class ReadOnlyFieldTests(_SyncedLocksTestBase):
    def test_the_pin_schedule_and_max_uses_stay_read_only(self):
        gateway = self._gateway()
        master = self._master(gateway)
        bodies = (
            {"code": "8642"},
            {"days_of_week": 3},
            {"window_start": "08:00", "window_end": "17:00"},
            {"max_uses": 2},
            {"is_active": False},
            # A lock change in the same save doesn't get them through.
            {"code": "8642", "add_lock_entity_ids": [self.BACK]},
        )
        for body in bodies:
            with self.subTest(body=body):
                response = self._patch_response(master, gateway, body)
                self.assertEqual(response.status_code, 400, response.content)
                details = response.json()["error"]["details"]
                self.assertTrue(set(details) & set(body) - {"add_lock_entity_ids"}, details)
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._slots(master), {self.FRONT: 1})


class DatedSyncedCodeTests(_SyncedLocksTestBase):
    def test_retiring_a_dated_synced_code_on_two_locks_clears_both(self):
        gateway = self._gateway()
        master = self._master(gateway)
        DoorCode.objects.filter(id=master.id).update(end_at=self._from_now(days=1))
        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        gateway.invoke_calls.clear()

        self._move(master, end_at=self._ago(minutes=1))
        self.assertEqual(self._enforce(gateway), 1)

        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertCountEqual(self._calls(gateway, "clear"), [(14, [1]), (12, [2])])
        self.assertEqual(self._lock_codes(gateway, 14), {})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: None, self.BACK: None})
        self.assertEqual(self._updated_event(master).metadata["reason"], "expired")


class StrandedCopyRuleTests(_SyncedLocksTestBase):
    """PR #211's stranded-copy rule must not take a slot latchpoint pushed a synced code into as a leftover."""

    def _expired_guest_once_pushed_into_back_slot_2(self, master: DoorCode) -> DoorCode:
        """A dated guest code with the master PIN, still on the Back Door, that was
        pushed into Back Door slot 2 before the master code's row was made."""
        guest = self._code(
            pin=self.PIN,
            slots={self.BACK: None},
            code_type=DoorCode.CodeType.TEMPORARY,
            end_at=self._ago(minutes=1),
            label="Guest",
        )
        pushed = DoorCodeEvent.objects.create(
            door_code=guest,
            lock_entity_id=self.BACK,
            event_type=DoorCodeEvent.EventType.CODE_SYNCED,
            metadata={"action": "pushed", "slot_index": 2},
        )
        DoorCodeEvent.objects.filter(id=pushed.id).update(created_at=master.created_at - timedelta(minutes=1))
        return guest

    def _assert_master_kept_and_flagged(self, master: DoorCode, guest: DoorCode, gateway) -> None:
        master.refresh_from_db()
        self.assertTrue(master.is_active)
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._lock_codes(gateway, 14), {1: self.PIN})
        # Only flagged, like any other code that shares the retiring code's PIN.
        flag = DoorCodeEvent.objects.get(door_code=guest, metadata__action="duplicate_pin_survives_retire")
        self.assertEqual(flag.metadata["duplicate_door_code_id"], master.id)

    def test_a_synced_codes_own_pushed_slot_is_not_retired_as_a_stranded_copy(self):
        master, gateway = self._master_on_both()
        guest = self._expired_guest_once_pushed_into_back_slot_2(master)

        self._enforce(gateway)

        self._assert_master_kept_and_flagged(master, guest, gateway)

    def test_it_holds_when_retention_pruned_the_master_codes_push_events(self):
        master, gateway = self._master_on_both()
        DoorCodeEvent.objects.filter(door_code=master).delete()
        guest = self._expired_guest_once_pushed_into_back_slot_2(master)

        self.assertIsNotNone(door_codes_uc.retire_door_code(code=guest, reason="expired", zwavejs=gateway))

        self.assertFalse(DoorCode.objects.get(id=guest.id).is_active)
        self._assert_master_kept_and_flagged(master, guest, gateway)

    def _stranded_copy(self) -> tuple[DoorCode, DoorCode, ClearFailingGateway]:
        """What #133 left on the Back Door: the guest pushed into slot 1, the slot forgotten,
        pushed again into slot 2, then slot 1 imported by lock sync."""
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True, drops_duplicates=False)
        guest = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            code_type=DoorCode.CodeType.TEMPORARY,
            end_at=self._from_now(days=1),
            lock_entity_ids=[self.BACK],
            actor_user=self.user,
            zwavejs=gateway,
        )
        DoorCodeLockAssignment.objects.filter(door_code=guest).update(
            slot_index=None, push_state=DoorCode.PushState.PENDING
        )
        lock_push_uc.push_door_code_to_assigned_locks(
            door_code=DoorCode.objects.prefetch_related("lock_assignments").get(id=guest.id), zwavejs=gateway
        )
        self._sync(gateway, self.BACK)
        copy = DoorCode.objects.get(lock_assignments__lock_entity_id=self.BACK, lock_assignments__slot_index=1)
        self.assertEqual(self._slots(guest), {self.BACK: 2})
        self.assertTrue(
            door_codes_uc._is_stranded_copy(original=guest, copy_id=copy.id, lock_entity_id=self.BACK, slot_index=1)
        )
        return guest, copy, gateway

    def test_a_stranded_copy_someone_added_a_lock_to_is_only_flagged(self):
        guest, copy, gateway = self._stranded_copy()
        self._patch(copy, gateway, {"add_lock_entity_ids": [self.SIDE]})
        self.assertEqual(self._slots(copy), {self.BACK: 1, self.SIDE: 1})

        self._move(guest, end_at=self._ago(minutes=1))
        self._enforce(gateway)

        copy.refresh_from_db()
        self.assertTrue(copy.is_active)
        self.assertEqual(self._slots(copy), {self.BACK: 1, self.SIDE: 1})
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})
        self.assertTrue(
            DoorCodeEvent.objects.filter(
                door_code=guest,
                metadata__action="duplicate_pin_survives_retire",
                metadata__duplicate_door_code_id=copy.id,
            ).exists()
        )

    def test_a_pending_retire_of_a_copy_someone_added_a_lock_to_since_leaves_it_alone(self):
        guest, copy, gateway = self._stranded_copy()
        self._move(guest, end_at=self._ago(minutes=1))
        with patch.object(door_codes_uc, "_retire_synced_copy", return_value=False):
            self._enforce(gateway)
        self.assertTrue(DoorCodeEvent.objects.filter(metadata__action="duplicate_retire_pending").exists())
        self._patch(copy, gateway, {"add_lock_entity_ids": [self.SIDE]})

        door_codes_uc.retry_pending_copy_retires(zwavejs=gateway)

        copy.refresh_from_db()
        self.assertTrue(copy.is_active)
        self.assertEqual(self._slots(copy), {self.BACK: 1, self.SIDE: 1})
        done = DoorCodeEvent.objects.get(door_code=guest, metadata__action="duplicate_retire_done")
        self.assertEqual(done.metadata["outcome"], "left_alone")
        self.assertTrue(
            DoorCodeEvent.objects.filter(door_code=guest, metadata__action="duplicate_pin_survives_retire").exists()
        )
        # Done, so the next tick doesn't try again.
        door_codes_uc.retry_pending_copy_retires(zwavejs=gateway)
        self.assertEqual(DoorCodeEvent.objects.filter(metadata__action="duplicate_retire_done").count(), 1)


class UnreadablePinStillRefusedOnlyForSyncedTests(_SyncedLocksTestBase):
    def test_a_manual_code_with_an_unreadable_pin_can_still_get_a_lock(self):
        # Manual codes are left as they were: the push records the bad PIN on the lock.
        gateway = self._gateway()
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin="not-a-token",
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.SIDE)

        self._patch(code, gateway, {"add_lock_entity_ids": [self.BACK]})

        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(set(self._slots(code)), {self.SIDE, self.BACK})


class StaleCacheSyncTests(_SyncedLocksTestBase):
    """A Back Door sync whose value cache still calls the pushed slot Available (the FakeGateway default)."""

    CACHE_UPDATES_ON_SET = False

    def _back(self, master: DoorCode) -> DoorCodeLockAssignment:
        return DoorCodeLockAssignment.objects.get(door_code=master, lock_entity_id=self.BACK)

    def test_a_stale_cache_neither_turns_the_code_off_nor_forgets_the_pushed_slot(self):
        master, gateway = self._master_on_both()
        # The push was confirmed by a live readback, but the cache hasn't caught up.
        self.assertNotIn((12, 2), gateway._cache_codes)

        result = self._sync(gateway, self.BACK)

        row = self._slot_row(result, 2)
        self.assertEqual((row.action, row.door_code_id), ("skipped", master.id))
        self.assertIn("slot_not_confirmed_empty", row.warnings)
        master.refresh_from_db()
        self.assertTrue(master.is_active)
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        self.assertEqual(self._back(master).push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(self._calls(gateway, "set"), [])

        # Nothing to push, and a Front Door sync leaves it on.
        gateway.invoke_calls.clear()
        self._push_pending(gateway)
        self._sync(gateway, self.FRONT)
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)

        # Removing the Back Door still clears the slot.
        self._patch(master, gateway, {"remove_lock_entity_ids": [self.BACK]})
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

    def test_a_pushed_slot_that_really_is_empty_is_pushed_again_without_turning_the_code_off(self):
        master, gateway = self._master_on_both()
        # Deleted at the Back Door.
        del gateway._lock_codes[(12, 2)]

        result = self._sync(gateway, self.BACK)

        row = self._slot_row(result, 2)
        self.assertEqual((row.action, row.door_code_id), ("updated", master.id))
        self.assertIn("slot_empty_repush", row.warnings)
        master.refresh_from_db()
        self.assertTrue(master.is_active)
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: None})
        self.assertEqual(self._back(master).push_state, DoorCode.PushState.PENDING)
        self.assertEqual(self._lock_codes(gateway, 14), {1: self.PIN})

        self._push_pending(gateway)

        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)

    def test_an_off_synced_code_keeps_its_pushed_slot(self):
        # Lock sync turned it off from the Front Door; the Back Door slot waits for it to come back on.
        master, gateway = self._master_on_both()
        DoorCode.objects.filter(id=master.id).update(is_active=False)

        self._sync(gateway, self.BACK)

        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_the_lock_it_was_imported_from_keeps_the_synced_rule(self):
        # Deleted at the Front Door, which is the lock's say for a synced code.
        master, gateway = self._master_on_both()
        del gateway._lock_codes[(14, 1)]
        del gateway._cache_codes[(14, 1)]

        self._sync(gateway, self.FRONT)

        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._slots(master), {self.FRONT: None, self.BACK: 2})
        self.assertFalse(any(c["method_name"] == "get" and c["node_id"] == 14 for c in gateway.invoke_calls))


# The tests above again with the FakeGateway default, where a set doesn't reach
# the value cache, so every sync after a push sees the pushed slot as Available.
class StaleCacheAddLockTests(AddLockTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheRemoveLockTests(RemoveLockTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheDatedSyncedCodeTests(DatedSyncedCodeTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheStrandedCopyRuleTests(StrandedCopyRuleTests):
    CACHE_UPDATES_ON_SET = False
