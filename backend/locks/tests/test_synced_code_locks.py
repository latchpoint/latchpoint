"""A synced code's locks can be added and removed like a manual code's (ADR 0082).

The real case: the master code was imported from the Front Door by lock sync,
so it's ``source=synced``, and the Back Door has to be added to it. Latchpoint
pushes its PIN to an added lock and clears it off a removed one, while the PIN,
schedule and max uses stay the lock's.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.db.models.signals import post_save
from django.urls import reverse
from integrations_zwavejs.manager import ZwavejsCommandError
from rest_framework.test import APITestCase

from accounts.models import User
from alarm.crypto import SettingsEncryption
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
        # A synced code's PIN is the lock's, so deleting the other code is the only way out.
        self.assertIn("Delete that code before adding that lock.", message)
        self.assertNotIn("different PIN", message)
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


class PushedSlotReconcileTests(_SyncedLocksTestBase):
    """A Back Door sync of the slot latchpoint pushed never decides the master code's state (ADR 0082).

    The Front Door, which it was imported from, is the lock's say. The Back
    Door's slot gets the manual code rule: marked pushed, skipped on another
    PIN, and never a source of the PIN, active flag, schedule or owner.
    """

    def _pin(self, code: DoorCode) -> str | None:
        code.refresh_from_db()
        return SettingsEncryption.get().decrypt(code.encrypted_pin) if code.encrypted_pin else None

    def _front_sync_turns_it_off(self, master: DoorCode, gateway: ClearFailingGateway) -> None:
        self._sync(gateway, self.FRONT)
        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._slots(master), {self.FRONT: None, self.BACK: 2})

    def test_a_back_door_sync_doesnt_turn_back_on_a_code_the_front_door_turned_off(self):
        # Scenario A: the PIN is deleted at the Front Door.
        master, gateway = self._master_on_both()
        del gateway._lock_codes[(14, 1)]
        del gateway._cache_codes[(14, 1)]
        self._front_sync_turns_it_off(master, gateway)

        self._sync(gateway, self.BACK)
        gateway.invoke_calls.clear()
        self._push_pending(gateway)

        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 14), {})
        # The Back Door keeps it until it's removed there in latchpoint (ADR-0109).
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self._patch(master, gateway, {"remove_lock_entity_ids": [self.BACK]})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

    def test_a_stale_front_cache_doesnt_end_in_a_second_copy_on_the_front_door(self):
        # Scenario B: the Front Door's cache drops slot 1 while the PIN is still in it.
        master, gateway = self._master_on_both()
        del gateway._cache_codes[(14, 1)]
        self._front_sync_turns_it_off(master, gateway)
        # The cache catches up and the next Front Door sync imports it as its own code.
        gateway._cache_codes[(14, 1)] = self.PIN
        self._sync(gateway, self.FRONT)
        slot_1 = DoorCode.objects.get(lock_assignments__lock_entity_id=self.FRONT, lock_assignments__slot_index=1)
        self.assertNotEqual(slot_1.id, master.id)

        self._sync(gateway, self.BACK)
        gateway.invoke_calls.clear()
        self._push_pending(gateway)

        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 14), {1: self.PIN})

    def test_another_pin_in_the_pushed_slot_is_never_taken_as_the_codes_pin(self):
        # Scenario C: someone programs a different PIN into Back Door slot 2 at the keypad.
        master, gateway = self._master_on_both()
        gateway._lock_codes[(12, 2)] = "5555"
        gateway._cache_codes[(12, 2)] = "5555"

        result = self._sync(gateway, self.BACK)

        row = self._slot_row(result, 2)
        self.assertEqual((row.action, row.door_code_id), ("skipped", master.id))
        self.assertIn("pin_mismatch", row.warnings)
        self.assertEqual(self._pin(master), self.PIN)
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        gateway.invoke_calls.clear()
        self._sync(gateway, self.FRONT)
        self._push_pending(gateway)
        self.assertEqual(self._pin(master), self.PIN)
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 14), {1: self.PIN})

    def test_a_back_door_sync_for_another_user_doesnt_take_the_code(self):
        master, gateway = self._master_on_both()
        gateway._cache_codes[(12, 2)] = self.PIN
        other = User.objects.create_user(email="other@example.com", password="pass")

        result = lock_config_sync_uc.sync_lock_config(
            lock_entity_id=self.BACK, target_user=other, actor_user=self.user, zwavejs=gateway
        )

        self.assertEqual(self._slot_row(result, 2).door_code_id, master.id)
        self.assertNotIn("owner_changed", self._slot_row(result, 2).warnings)
        self.assertEqual(DoorCode.objects.get(id=master.id).user_id, self.user.id)

    def test_the_front_door_still_gives_the_code_its_pin_and_owner(self):
        # The lock it was imported from keeps the synced rule.
        master, gateway = self._master_on_both()
        gateway._lock_codes[(14, 1)] = "8642"
        gateway._cache_codes[(14, 1)] = "8642"
        other = User.objects.create_user(email="other@example.com", password="pass")

        lock_config_sync_uc.sync_lock_config(
            lock_entity_id=self.FRONT, target_user=other, actor_user=self.user, zwavejs=gateway
        )

        self.assertEqual(self._pin(master), "8642")
        self.assertEqual(DoorCode.objects.get(id=master.id).user_id, other.id)


class CopyRetireRaceTests(_SyncedLocksTestBase):
    """A lock added to a stranded copy right before its pending retire takes the copy's locks."""

    def _pending_copy_retire(self):
        guest, copy, gateway = StrandedCopyRuleTests._stranded_copy(self)
        self._move(guest, end_at=self._ago(minutes=1))
        with patch.object(door_codes_uc, "_retire_synced_copy", return_value=None):
            self._enforce(gateway)
        self.assertTrue(DoorCodeEvent.objects.filter(metadata__action="duplicate_retire_pending").exists())
        return guest, copy, gateway

    def _retry_with_an_add_landing_first(self, copy: DoorCode, gateway: ClearFailingGateway) -> None:
        real = door_codes_uc._retire_synced_copy

        def add_then_retire(**kwargs):
            # After retry_pending_copy_retires picked up the pending retire and
            # before _retire_synced_copy takes the copy's lock_sync: locks, so
            # only a check made under those locks can see it.
            door_codes_uc.update_door_code(
                code=door_codes_uc.get_door_code_for_read(code_id=copy.id),
                changes={"add_lock_entity_ids": [self.SIDE]},
                actor_user=self.user,
                zwavejs=gateway,
            )
            return real(**kwargs)

        with patch.object(door_codes_uc, "_retire_synced_copy", side_effect=add_then_retire):
            door_codes_uc.retry_pending_copy_retires(zwavejs=gateway)

    def _assert_left_alone(self, guest: DoorCode, copy: DoorCode) -> None:
        copy.refresh_from_db()
        self.assertTrue(copy.is_active)
        self.assertEqual(self._slots(copy)[self.BACK], 1)
        done = DoorCodeEvent.objects.get(door_code=guest, metadata__action="duplicate_retire_done")
        self.assertEqual(done.metadata["outcome"], "left_alone")
        self.assertTrue(
            DoorCodeEvent.objects.filter(door_code=guest, metadata__action="duplicate_pin_survives_retire").exists()
        )

    def test_an_add_that_lands_before_the_retire_takes_the_locks_keeps_the_copy(self):
        guest, copy, gateway = self._pending_copy_retire()

        self._retry_with_an_add_landing_first(copy, gateway)

        self._assert_left_alone(guest, copy)
        self.assertEqual(self._slots(copy), {self.BACK: 1, self.SIDE: 1})
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})

    def test_an_add_whose_push_is_only_queued_keeps_the_copy_too(self):
        guest, copy, gateway = self._pending_copy_retire()

        with patch.object(lock_push_uc, "push_task_running", return_value=True):
            self._retry_with_an_add_landing_first(copy, gateway)

        self._assert_left_alone(guest, copy)
        side = DoorCodeLockAssignment.objects.get(door_code=copy, lock_entity_id=self.SIDE)
        self.assertIsNotNone(side.push_requested_at)
        self.assertIsNone(side.last_push_attempt_at)

    def test_an_add_that_lands_while_the_original_retires_keeps_the_copy(self):
        # retire_door_code classed the copy as stranded, then a lock gets added to
        # it (no push task in this process, so its push is made inline and stamps
        # the lock) before _retire_synced_copy takes the copy's locks.
        guest, copy, gateway = StrandedCopyRuleTests._stranded_copy(self)
        self._move(guest, end_at=self._ago(minutes=1))
        real = door_codes_uc._is_stranded_copy
        added: list[bool] = []

        def stranded_then_add(**kwargs):
            stranded = real(**kwargs)
            if stranded and not added:
                added.append(True)
                door_codes_uc.update_door_code(
                    code=door_codes_uc.get_door_code_for_read(code_id=copy.id),
                    changes={"add_lock_entity_ids": [self.SIDE]},
                    actor_user=self.user,
                    zwavejs=gateway,
                )
            return stranded

        with patch.object(door_codes_uc, "_is_stranded_copy", side_effect=stranded_then_add):
            self._enforce(gateway)

        self.assertEqual(added, [True])
        self.assertFalse(DoorCode.objects.get(id=guest.id).is_active)
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
        self.assertFalse(DoorCodeEvent.objects.filter(metadata__action="duplicate_retire_pending").exists())


class IntegrityRaceOnPushedSlotTests(_SyncedLocksTestBase):
    """The sync's IntegrityError fallback, when the winner is a synced code on a slot latchpoint pushed."""

    def _sync_back_losing_slot_2_to(self, master: DoorCode, gateway: ClearFailingGateway):
        # The master's Back Door slot is put back between the sync's lookup of
        # slot 2 and its insert of a new code's assignment there.
        back = DoorCodeLockAssignment.objects.get(door_code=master, lock_entity_id=self.BACK)
        DoorCodeLockAssignment.objects.filter(id=back.id).update(slot_index=None)

        def take_slot_first(sender, instance, created, **kwargs):
            if created and instance.source == DoorCode.Source.SYNCED:
                DoorCodeLockAssignment.objects.filter(id=back.id).update(slot_index=2)

        post_save.connect(take_slot_first, sender=DoorCode)
        try:
            return self._sync(gateway, self.BACK)
        finally:
            post_save.disconnect(take_slot_first, sender=DoorCode)

    def test_another_pin_is_skipped_not_adopted(self):
        master, gateway = self._master_on_both()
        gateway._lock_codes[(12, 2)] = "5555"
        gateway._cache_codes[(12, 2)] = "5555"

        result = self._sync_back_losing_slot_2_to(master, gateway)

        row = self._slot_row(result, 2)
        self.assertEqual((row.action, row.door_code_id), ("skipped", master.id))
        self.assertIn("integrity_race", row.warnings)
        self.assertIn("pin_mismatch", row.warnings)
        self.assertEqual(lock_push_uc.decrypt_pin_or_none(DoorCode.objects.get(id=master.id)), self.PIN)

    def test_an_off_code_is_not_turned_on(self):
        master, gateway = self._master_on_both()
        gateway._cache_codes[(12, 2)] = self.PIN
        DoorCode.objects.filter(id=master.id).update(is_active=False)

        result = self._sync_back_losing_slot_2_to(master, gateway)

        row = self._slot_row(result, 2)
        self.assertEqual(row.door_code_id, master.id)
        self.assertIn("integrity_race", row.warnings)
        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)


class DeleteTests(_SyncedLocksTestBase):
    """Deleting a synced code latchpoint pushed to an added lock goes the manual code's way (ADR 0082 §3)."""

    def _delete_response(self, code: DoorCode, gateway: ClearFailingGateway):
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            return self.client.delete(
                reverse("door-code-detail", args=[code.id]), {"reauth_password": "pass"}, format="json"
            )

    def test_an_unconfirmed_slot_on_the_added_lock_that_cant_be_checked_refuses_the_delete(self):
        # Scenario A: every readback on the Back Door times out, the push's and the delete's.
        timeouts = [ZwavejsCommandError("driver TimeoutError after 5.0s")] * 20
        gateway = self._gateway(get_responses={12: timeouts})
        master = self._master(gateway)
        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: None})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

        response = self._delete_response(master, gateway)

        self.assertEqual(response.status_code, 502, response.content)
        self.assertIn("wasn't deleted and is now off", response.json()["error"]["message"])
        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._slots(master), {self.FRONT: None, self.BACK: None})
        self.assertEqual(self._lock_codes(gateway, 14), {})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=master), [self.BACK])
        # A Back Door sync meanwhile leaves the slot to the master code instead of
        # importing it. With a stale cache it doesn't see the slot at all.
        result = self._sync(gateway, self.BACK)
        self.assertEqual(result.created, 0)
        rows = [row.door_code_id for row in result.slots if row.slot_index == 2]
        self.assertEqual(rows, [master.id] if self.CACHE_UPDATES_ON_SET else [])

        # Once the Back Door answers, deleting it again clears the slot.
        gateway._get_scripts[12] = []
        response = self._delete_response(master, gateway)

        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(DoorCode.objects.filter(id=master.id).exists())
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

    def test_a_failed_clear_on_the_added_lock_is_recorded_and_retried(self):
        # Scenario B: the Front Door's slot clears, the Back Door's doesn't.
        master, gateway = self._master_on_both()
        gateway.clear_fails_on = {12}

        response = self._delete_response(master, gateway)

        self.assertEqual(response.status_code, 502, response.content)
        self.assertIn("wasn't deleted and is now off", response.json()["error"]["message"])
        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._lock_codes(gateway, 14), {})
        self.assertEqual(self._slots(master), {self.FRONT: None, self.BACK: 2})
        [failure] = lock_push_uc.unresolved_clear_failures(door_code=master)
        self.assertEqual((failure.lock_entity_id, failure.slot_index), (self.BACK, 2))

        # The scheduler's clear retry takes it off once the Back Door answers.
        gateway.clear_fails_on = set()
        self._push_pending(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: None, self.BACK: None})
        self.assertEqual(self._calls(gateway, "set"), [])

        self.assertEqual(self._delete_response(master, gateway).status_code, 204)
        self.assertFalse(DoorCode.objects.filter(id=master.id).exists())

    def test_a_synced_code_on_its_import_lock_only_still_fails_fast(self):
        gateway = self._gateway()
        master = self._master(gateway)
        gateway.clear_fails_on = {14}

        response = self._delete_response(master, gateway)

        self.assertEqual(response.status_code, 502, response.content)
        self.assertNotIn("is now off", response.json()["error"]["message"])
        master.refresh_from_db()
        self.assertTrue(master.is_active)
        self.assertEqual(self._slots(master), {self.FRONT: 1})
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=master), [])

    def test_an_unconfirmed_slot_on_a_lock_removed_since_still_refuses_the_delete(self):
        # The Back Door's push wrote slot 2 but every readback timed out, so the
        # lock never got a slot. Then the Back Door was removed while it still
        # didn't answer. Only the Front Door's unstamped assignment is left, but
        # the Back Door's slot is still on record.
        timeouts = [ZwavejsCommandError("driver TimeoutError after 5.0s")] * 40
        gateway = self._gateway(get_responses={12: timeouts})
        master = self._master(gateway)
        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})
        self._patch(master, gateway, {"remove_lock_entity_ids": [self.BACK]})
        self.assertEqual(self._slots(master), {self.FRONT: 1})
        self.assertFalse(lock_push_uc.has_lock_pushed_by_latchpoint(door_code_id=master.id))
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

        response = self._delete_response(master, gateway)

        self.assertEqual(response.status_code, 502, response.content)
        self.assertIn("wasn't deleted and is now off", response.json()["error"]["message"])
        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._lock_codes(gateway, 14), {})

        gateway._get_scripts[12] = []
        self.assertEqual(self._delete_response(master, gateway).status_code, 204)
        self.assertFalse(DoorCode.objects.filter(id=master.id).exists())
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

    def test_a_recorded_failed_clear_is_retried_by_the_delete(self):
        # A slot latchpoint still has a failed clear for, on a lock the code has no assignment on.
        gateway = self._gateway()
        master = self._master(gateway)
        gateway._lock_codes[(12, 3)] = self.PIN
        lock_push_uc.record_clear_failure(
            door_code=master,
            lock_entity_id=self.BACK,
            slot_index=3,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin=self.PIN,
        )
        gateway.invoke_calls.clear()

        self.assertEqual(self._delete_response(master, gateway).status_code, 204)

        self.assertIn((12, [3]), self._calls(gateway, "clear"))
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(self._lock_codes(gateway, 14), {})

    def test_an_added_lock_whose_push_is_only_queued_is_deleted_like_a_manual_code(self):
        gateway = self._gateway()
        master = self._master(gateway)
        with patch.object(lock_push_uc, "push_task_running", return_value=True):
            self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})
        back = DoorCodeLockAssignment.objects.get(door_code=master, lock_entity_id=self.BACK)
        self.assertIsNotNone(back.push_requested_at)
        self.assertIsNone(back.last_push_attempt_at)
        gateway.clear_fails_on = {14}

        response = self._delete_response(master, gateway)

        self.assertEqual(response.status_code, 502, response.content)
        self.assertIn("wasn't deleted and is now off", response.json()["error"]["message"])
        master.refresh_from_db()
        self.assertFalse(master.is_active)
        [failure] = lock_push_uc.unresolved_clear_failures(door_code=master)
        self.assertEqual((failure.lock_entity_id, failure.slot_index), (self.FRONT, 1))

    def test_retry_on_an_off_synced_code_says_what_to_do(self):
        gateway = self._gateway()
        master = self._master(gateway)
        DoorCode.objects.filter(id=master.id).update(is_active=False)

        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.post(reverse("door-code-push", args=[master.id]), {}, format="json")

        self.assertEqual(response.status_code, 409, response.content)
        message = response.json()["error"]["message"]
        self.assertIn("delete it again", message)
        self.assertNotIn("Turn it on", message)


class ImportLockChangeTests(_SyncedLocksTestBase):
    """A new PIN or schedule lock sync takes from the Front Door goes on to the added Back Door (issue #220)."""

    NEW_PIN = "8642"
    WEEKDAYS = 0b0011111  # Mon-Fri
    MON_WED = 0b0000101

    def _pin(self, code: DoorCode) -> str | None:
        code.refresh_from_db()
        return SettingsEncryption.get().decrypt(code.encrypted_pin) if code.encrypted_pin else None

    def _back(self, master: DoorCode) -> DoorCodeLockAssignment:
        return DoorCodeLockAssignment.objects.get(door_code=master, lock_entity_id=self.BACK)

    def _change_front_pin(self, gateway: ClearFailingGateway, pin: str, *, on_lock: bool = True) -> None:
        """Someone programs ``pin`` into Front Door slot 1. ``on_lock=False`` only changes the value cache."""
        gateway._cache_codes[(14, 1)] = pin
        if on_lock:
            gateway._lock_codes[(14, 1)] = pin

    def _sync_front(self, gateway: ClearFailingGateway, *, days: int | None = None, start: str = "08:00:00"):
        """A Front Door sync whose slot 1 has a ``days`` schedule from ``start`` to 18:00 (none when ``None``)."""
        schedule = {1: {"days_of_week": days, "window_start": start, "window_end": "18:00:00"}} if days else {}
        with (
            patch.object(lock_config_sync_uc, "_extract_weekday_schedule_windows", return_value=(schedule, {})),
            patch("scheduler.runner.wake_task") as wake,
            # Only the wakes are wanted from the commit callbacks, not the rules dispatcher.
            patch("alarm.dispatcher.notify_entities_changed"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = self._sync(gateway, self.FRONT)
        self.woken = [call.args[0] for call in wake.call_args_list]
        return result

    def _push_requested(self, gateway: ClearFailingGateway) -> int:
        from locks.tasks import push_requested_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            return push_requested_door_codes()

    @staticmethod
    def _schedule_calls(gateway: ClearFailingGateway) -> list[tuple[int, int, int]]:
        """``(node, userId, weekday)`` for every CC 78 ``setDailyRepeatingSchedule``."""
        return [
            (c["node_id"], c["args"][0]["userId"], c["args"][1]["weekdays"][0])
            for c in gateway.invoke_calls
            if c["command_class"] == 78 and c["method_name"] == "setDailyRepeatingSchedule"
        ]

    def _assert_back_door_left_alone(self, master: DoorCode, gateway: ClearFailingGateway) -> None:
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=master), [])
        gateway.invoke_calls.clear()
        self._push_pending(gateway)
        self._push_requested(gateway)
        self.assertEqual([c for c in gateway.invoke_calls if c["node_id"] == 12], [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})

    def test_a_new_pin_goes_on_to_the_added_lock_and_the_old_one_comes_off_it(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)

        result = self._sync_front(gateway)

        row = self._slot_row(result, 1)
        self.assertEqual((row.action, row.door_code_id), ("updated", master.id))
        self.assertIn("sent_to_other_locks", row.warnings)
        self.assertEqual(self._pin(master), self.NEW_PIN)
        # Nothing is sent to the Back Door while the sync holds the Front Door.
        self.assertEqual([c for c in gateway.invoke_calls if c["node_id"] == 12 and c["method_name"] != "get"], [])
        self.assertEqual([f.slot_index for f in lock_push_uc.unresolved_clear_failures(door_code=master)], [2])
        self.assertEqual(set(self.woken), {"push_pending_door_codes"})
        master.refresh_from_db()
        self.assertEqual(master.push_state, DoorCode.PushState.PENDING)
        # Only queued, so it reads as waiting, not as a failure, and no code_failed is logged.
        self.assertEqual(master.last_push_error, f"Waiting to clear slot 2 on {self.BACK} before sending the new PIN")
        self.assertFalse(self._clear_failed_events(master).exists())
        synced = DoorCodeEvent.objects.filter(door_code=master, lock_entity_id=self.FRONT).latest("id")
        self.assertEqual(synced.metadata["sent_to_lock_entity_ids"], [self.BACK])

        gateway.invoke_calls.clear()
        self._push_pending(gateway)

        # The old PIN is cleared off slot 2 and the new one goes in its place.
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._calls(gateway, "set"), [(12, [2, 1, self.NEW_PIN])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(self._lock_codes(gateway, 14), {1: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        master.refresh_from_db()
        self.assertEqual(master.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(master.source, DoorCode.Source.SYNCED)

        # A Back Door sync no longer finds another PIN in the code's slot.
        row = self._slot_row(self._sync(gateway, self.BACK), 2)
        self.assertEqual(row.door_code_id, master.id)
        self.assertNotIn("pin_mismatch", row.warnings)
        self.assertEqual(self._pin(master), self.NEW_PIN)

    def test_a_schedule_change_goes_on_to_the_added_lock(self):
        master, gateway = self._master_on_both()

        result = self._sync_front(gateway, days=self.WEEKDAYS)

        self.assertIn("sent_to_other_locks", self._slot_row(result, 1).warnings)
        master.refresh_from_db()
        self.assertEqual((master.days_of_week, master.window_start.isoformat()), (self.WEEKDAYS, "08:00:00"))
        # Only the schedule is owed, so the slot and the PIN in it stay.
        back = self._back(master)
        self.assertEqual((back.slot_index, back.schedule_pending), (2, True))
        self.assertIsNotNone(back.push_requested_at)
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=master), [])
        self.assertEqual([c for c in gateway.invoke_calls if c["node_id"] == 12 and c["method_name"] != "get"], [])

        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(sorted(self._schedule_calls(gateway)), [(12, 2, day) for day in (1, 2, 3, 4, 5)])
        back = self._back(master)
        self.assertEqual((back.slot_index, back.schedule_pending, back.push_state), (2, False, "pushed"))
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

        # A later window on the same days goes the same way.
        gateway.invoke_calls.clear()
        self._sync_front(gateway, days=self.WEEKDAYS, start="09:00:00")
        self._push_requested(gateway)
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(len(self._schedule_calls(gateway)), 5)

    def test_a_schedule_that_drops_days_is_cleared_and_pushed_again(self):
        # Sending the new days only would leave the dropped days' windows on the lock.
        master, gateway = self._master_on_both()
        self._sync_front(gateway, days=self.WEEKDAYS)
        self._push_requested(gateway)

        for days, expected_weekdays in ((self.MON_WED, [1, 3]), (None, [])):
            with self.subTest(days=days):
                gateway.invoke_calls.clear()
                self._sync_front(gateway, days=days)

                self.assertEqual([f.slot_index for f in lock_push_uc.unresolved_clear_failures(door_code=master)], [2])
                self.assertEqual(set(self.woken), {"push_pending_door_codes"})
                self._push_pending(gateway)

                self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
                self.assertEqual(self._calls(gateway, "set"), [(12, [2, 1, self.PIN])])
                self.assertEqual(sorted(w for _n, _u, w in self._schedule_calls(gateway)), expected_weekdays)
                self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
                self.assertEqual(DoorCode.objects.get(id=master.id).push_state, DoorCode.PushState.PUSHED)

    def test_a_front_door_that_masks_its_codes_sends_nothing(self):
        master, gateway = self._master_on_both()
        gateway._cache_codes[(14, 1)] = "****"

        result = self._sync_front(gateway)

        self.assertNotIn("sent_to_other_locks", self._slot_row(result, 1).warnings)
        self.assertEqual(self._pin(master), self.PIN)
        self.assertEqual(self.woken, [])
        self._assert_back_door_left_alone(master, gateway)

    def test_a_new_pin_only_the_value_cache_has_is_not_taken_or_sent(self):
        # A stale or dropped write in Z-Wave JS's cache: the lock itself still has the old PIN.
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN, on_lock=False)

        result = self._sync_front(gateway)

        row = self._slot_row(result, 1)
        self.assertIn("pin_change_unconfirmed", row.warnings)
        self.assertNotIn("sent_to_other_locks", row.warnings)
        self.assertEqual(self._pin(master), self.PIN)
        self._assert_back_door_left_alone(master, gateway)

        # Once the lock really has it, the next sync takes it and sends it on.
        self._change_front_pin(gateway, self.NEW_PIN)
        self.assertIn("sent_to_other_locks", self._slot_row(self._sync_front(gateway), 1).warnings)
        self._push_pending(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_a_readback_that_doesnt_answer_keeps_the_old_pin(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        gateway._get_scripts[14] = [ZwavejsCommandError("driver TimeoutError after 5.0s")] * 3

        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertIn("pin_change_unconfirmed", row.warnings)
        self.assertEqual(self._pin(master), self.PIN)
        self._assert_back_door_left_alone(master, gateway)

    def test_a_new_pin_another_code_already_has_on_the_added_lock_takes_the_code_off_that_lock(self):
        # The Back Door's slot 1 code has that PIN, so a push would put it in a second slot (#188).
        # The old PIN was changed on purpose, so it still comes off.
        master, gateway = self._master_on_both()
        other = DoorCode.objects.get(lock_assignments__lock_entity_id=self.BACK, lock_assignments__slot_index=1)
        self._change_front_pin(gateway, OTHER_PIN)

        result = self._sync_front(gateway)

        row = self._slot_row(result, 1)
        self.assertIn("pin_held_on_other_lock", row.warnings)
        self.assertNotIn("sent_to_other_locks", row.warnings)
        self.assertEqual(self._pin(master), OTHER_PIN)
        synced = DoorCodeEvent.objects.filter(door_code=master, lock_entity_id=self.FRONT).latest("id")
        self.assertEqual(synced.metadata["pin_held_on_lock_entity_ids"], [self.BACK])
        gateway.invoke_calls.clear()

        self._push_pending(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.push_state), (None, DoorCode.PushState.FAILED))
        # The id isn't checked: stored errors mask any run of 4-8 digits, and test ids run that high on Postgres.
        self.assertIn(f"{self.BACK} already has this PIN in slot 1 as door code ", back.last_push_error)
        self.assertIn('("Slot 1"), so this code is off that lock', back.last_push_error)
        self.assertIn("Delete that code, then Retry", back.last_push_error)
        self.assertEqual(DoorCode.objects.get(id=master.id).push_state, DoorCode.PushState.FAILED)

        # Once the other code is deleted, Retry puts the code back on the Back Door.
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.delete(
                reverse("door-code-detail", args=[other.id]), {"reauth_password": "pass"}, format="json"
            )
        self.assertEqual(response.status_code, 204, response.content)
        door_codes_uc.retry_push_door_code(
            code=DoorCode.objects.get(id=master.id), actor_user=self.user, zwavejs=gateway
        )
        self.assertEqual(list(self._lock_codes(gateway, 12).values()), [OTHER_PIN])
        self.assertIsNotNone(self._back(master).slot_index)

    def test_an_off_code_keeps_its_old_pin_on_the_added_lock_until_its_back_on(self):
        # ADR-0109: a code the Front Door turns off keeps its PIN on the added locks.
        master, gateway = self._master_on_both()
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)

        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._pin(master), self.NEW_PIN)
        gateway.invoke_calls.clear()
        self._push_pending(gateway)
        self.assertEqual([c for c in gateway.invoke_calls if c["node_id"] == 12], [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})

        disabled.clear()
        self._sync_front(gateway)
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self._push_pending(gateway)
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})

    def test_an_off_code_keeps_its_window_on_the_added_lock_until_its_back_on(self):
        master, gateway = self._master_on_both()
        self._sync_front(gateway, days=self.WEEKDAYS)
        self._push_requested(gateway)
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)

        self._sync_front(gateway, days=self.MON_WED)

        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)
        gateway.invoke_calls.clear()
        self._push_pending(gateway)
        self._push_requested(gateway)
        self.assertEqual([c for c in gateway.invoke_calls if c["node_id"] == 12], [])

        disabled.clear()
        self._sync_front(gateway, days=self.MON_WED)
        self._push_pending(gateway)
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(sorted(w for _n, _u, w in self._schedule_calls(gateway)), [1, 3])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

    def test_an_unconfirmed_push_to_the_added_lock_has_its_old_pin_cleared(self):
        # Every readback on the Back Door times out, so the PIN is only on record as an attempt in slot 2.
        gateway = self._gateway(get_responses={12: [ZwavejsCommandError("driver TimeoutError after 5.0s")] * 3})
        master = self._master(gateway)
        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: None})
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)

        failures = lock_push_uc.unresolved_clear_failures(door_code=master)
        self.assertEqual([(f.lock_entity_id, f.slot_index, f.unconfirmed) for f in failures], [(self.BACK, 2, True)])
        gateway.invoke_calls.clear()
        self._push_pending(gateway)
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})

    # Review of PR #223: races with a push in flight, checks before a clear, the
    # import lock's say, schedule readbacks and the wording.

    def _change_twice_during_the_re_push(self, *, after_marker: bool) -> None:
        """The Front Door changes twice, the second sync landing while the first change's push runs.

        That push has read the PIN and not committed the slot yet: before its
        ``set``, or after its unconfirmed attempt marker (``after_marker``).
        """
        latest = "1357"
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)

        def change_again():
            self._change_front_pin(gateway, latest)
            self._sync_front(gateway)

        if after_marker:
            original = lock_push_uc._record_unconfirmed_slot_attempt
            fired: list[bool] = []

            def record_then_change(**kwargs):
                marker = original(**kwargs)
                if kwargs.get("reason") == "PIN set on the lock, slot not saved yet" and not fired:
                    fired.append(True)
                    change_again()
                return marker

            with patch.object(lock_push_uc, "_record_unconfirmed_slot_attempt", record_then_change):
                self._push_pending(gateway)
        else:
            self._before_call(gateway, node_id=12, command_class=99, method_name="set", hook=change_again)
            self._push_pending(gateway)

        self.assertEqual(self._pin(master), latest)
        # The slot the stale push filled is kept on record and queued for a clear, not marked pushed.
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual([f.slot_index for f in lock_push_uc.unresolved_clear_failures(door_code=master)], [2])
        self.assertNotEqual(self._back(master).push_state, DoorCode.PushState.PUSHED)

        self._push_pending(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: latest})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        self.assertEqual(DoorCode.objects.get(id=master.id).push_state, DoorCode.PushState.PUSHED)

    def test_a_pin_change_landing_before_the_re_push_writes_ends_with_the_newest_pin(self):
        self._change_twice_during_the_re_push(after_marker=False)

    def test_a_pin_change_landing_after_the_re_push_wrote_ends_with_the_newest_pin(self):
        self._change_twice_during_the_re_push(after_marker=True)

    def test_a_schedule_change_landing_while_the_last_one_goes_out_isnt_lost(self):
        master, gateway = self._master_on_both()
        self._sync_front(gateway, days=self.WEEKDAYS)
        self._before_call(
            gateway,
            node_id=12,
            command_class=78,
            method_name="setDailyRepeatingSchedule",
            hook=lambda: self._sync_front(gateway, days=self.WEEKDAYS, start="09:00:00"),
        )

        self._push_requested(gateway)

        back = self._back(master)
        self.assertEqual((back.schedule_pending, back.push_state), (True, DoorCode.PushState.PENDING))
        gateway.invoke_calls.clear()
        self._push_requested(gateway)
        self.assertEqual({c["args"][1]["startHour"] for c in self._schedule_calls_raw(gateway)}, {9})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.schedule_pending, back.push_state), (2, False, "pushed"))

    def test_a_slot_holding_a_pin_latchpoint_never_set_is_let_go_not_cleared(self):
        # Someone typed another PIN into the Back Door's slot 2 (the pin_mismatch case).
        master, gateway = self._master_on_both()
        gateway._lock_codes[(12, 2)] = "5555"
        gateway._cache_codes[(12, 2)] = "5555"
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        gateway.invoke_calls.clear()

        self._push_pending(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: "5555", 3: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 3})
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=master), [])

    def test_a_back_door_that_masks_its_codes_still_gets_the_old_pin_cleared(self):
        master, gateway = self._master_on_both()
        self._mask_reads(gateway, node=12)
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        gateway.invoke_calls.clear()

        self._push_pending(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_a_clear_stuck_on_the_added_lock_doesnt_freeze_the_front_door(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        gateway.clear_fails_on.add(12)
        self._push_pending(gateway)
        # Now a real failure on record, and the code's clear retries are at the cap.
        self.assertTrue(self._clear_failed_events(master).exists())
        self.assertTrue(DoorCode.objects.get(id=master.id).last_push_error.startswith("Couldn't clear slot 2"))
        DoorCode.objects.filter(id=master.id).update(push_attempt_count=lock_push_uc._push_max_attempts())

        # The Front Door still decides the PIN...
        self._change_front_pin(gateway, "1357")
        row = self._slot_row(self._sync_front(gateway), 1)
        self.assertNotEqual(row.action, "skipped")
        self.assertEqual(self._pin(master), "1357")

        # ...and a PIN deleted there still turns the code off.
        del gateway._lock_codes[(14, 1)]
        del gateway._cache_codes[(14, 1)]
        self._sync_front(gateway)
        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)

    def test_any_other_clear_on_another_lock_still_holds_the_front_door_back(self):
        # PR #165: a code latchpoint is clearing somewhere isn't given a PIN or turned on by a stale read.
        master, gateway = self._master_on_both()
        lock_push_uc.record_clear_failure(
            door_code=master,
            lock_entity_id=self.BACK,
            slot_index=2,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin=self.PIN,
        )
        self._change_front_pin(gateway, self.NEW_PIN)

        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertEqual((row.action, row.warnings[-1]), ("skipped", "clear_outstanding"))
        self.assertEqual(self._pin(master), self.PIN)

    def test_a_schedule_from_the_value_cache_only_goes_out_once_the_lock_confirms_it(self):
        master, gateway = self._master_on_both()
        live: list = [None]
        self._front_schedule_from_cache(gateway, live)

        # The cache says Mon-Fri, the lock has no schedule.
        row = self._slot_row(self._sync_front(gateway, days=self.WEEKDAYS), 1)
        self.assertIn("schedule_change_unconfirmed", row.warnings)
        self.assertNotIn("sent_to_other_locks", row.warnings)
        self.assertIsNone(DoorCode.objects.get(id=master.id).days_of_week)
        self.assertFalse(self._back(master).schedule_pending)

        live[0] = (self.WEEKDAYS, (8, 0), (18, 0))
        row = self._slot_row(self._sync_front(gateway, days=self.WEEKDAYS), 1)
        self.assertIn("sent_to_other_locks", row.warnings)
        self.assertEqual(DoorCode.objects.get(id=master.id).days_of_week, self.WEEKDAYS)
        self.assertTrue(self._back(master).schedule_pending)
        self._push_requested(gateway)

        # A schedule the cache alone says is gone is never sent on either.
        row = self._slot_row(self._sync_front(gateway, days=None), 1)
        self.assertIn("schedule_change_unconfirmed", row.warnings)
        self.assertEqual(DoorCode.objects.get(id=master.id).days_of_week, self.WEEKDAYS)
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=master), [])

        live[0] = None
        self._sync_front(gateway, days=None)
        self.assertIsNone(DoorCode.objects.get(id=master.id).days_of_week)
        self.assertEqual([f.slot_index for f in lock_push_uc.unresolved_clear_failures(door_code=master)], [2])

    def test_the_scheduler_is_woken_once_the_sync_commits(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)

        with patch("scheduler.runner.wake_task") as wake, patch("alarm.dispatcher.notify_entities_changed"):
            with self.captureOnCommitCallbacks() as callbacks:
                self._sync(gateway, self.FRONT)
                self.assertEqual(wake.call_count, 0)
            self.assertEqual(wake.call_count, 0)
            for callback in callbacks:
                callback()
        self.assertIn("push_pending_door_codes", [call.args[0] for call in wake.call_args_list])

    def test_a_code_at_the_clear_retry_cap_gets_a_fresh_start_for_the_change(self):
        master, gateway = self._master_on_both()
        DoorCode.objects.filter(id=master.id).update(push_attempt_count=lock_push_uc._push_max_attempts())
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)
        self._push_pending(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_sent_to_other_locks_only_shows_when_something_was_queued(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self.assertIn("sent_to_other_locks", self._slot_row(self._sync_front(gateway), 1).warnings)

        # The Back Door's clear is still queued and pushes whatever the PIN is by then.
        self._change_front_pin(gateway, "1357")
        row = self._slot_row(self._sync_front(gateway), 1)
        self.assertEqual(self._pin(master), "1357")
        self.assertNotIn("sent_to_other_locks", row.warnings)
        self._push_pending(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: "1357"})

    def _clear_failed_events(self, code: DoorCode):
        return DoorCodeEvent.objects.filter(
            door_code=code, event_type=DoorCodeEvent.EventType.CODE_FAILED, metadata__action="clear_failed"
        )

    @staticmethod
    def _schedule_calls_raw(gateway: ClearFailingGateway) -> list[dict]:
        return [
            c
            for c in gateway.invoke_calls
            if c["command_class"] == 78 and c["method_name"] == "setDailyRepeatingSchedule"
        ]

    @staticmethod
    def _before_call(gateway: ClearFailingGateway, *, node_id: int, command_class: int, method_name: str, hook) -> None:
        """Run ``hook()`` once, right before the first matching ``invoke_cc_api`` call goes out."""
        invoke = gateway.invoke_cc_api
        fired: list[bool] = []

        def invoke_cc_api(**kwargs):
            if (kwargs["node_id"], kwargs["command_class"], kwargs["method_name"]) == (
                node_id,
                command_class,
                method_name,
            ) and not fired:
                fired.append(True)
                hook()
            return invoke(**kwargs)

        gateway.invoke_cc_api = invoke_cc_api

    @staticmethod
    def _mask_reads(gateway: ClearFailingGateway, *, node: int) -> None:
        """Make ``node`` hide its codes, in the value cache and in a live ``get``."""
        get_value, handle = gateway.node_get_value, gateway._handle_user_code_call

        def node_get_value(*, node_id: int, value_id: dict, timeout_seconds: float = 5.0):
            value = get_value(node_id=node_id, value_id=value_id, timeout_seconds=timeout_seconds)
            return "**********" if node_id == node and value_id.get("property") == "userCode" and value else value

        def handle_user_code_call(*, node_id: int, method_name: str, args: list):
            response = handle(node_id=node_id, method_name=method_name, args=args)
            if method_name == "get" and node_id == node and response.get("userCode"):
                return {**response, "userCode": "**********"}
            return response

        gateway.node_get_value = node_get_value
        gateway._handle_user_code_call = handle_user_code_call

    @staticmethod
    def _front_schedule_from_cache(gateway: ClearFailingGateway, live: list) -> None:
        """The Front Door exposes CC 78 values, so a sync reads its schedules from the value cache.

        A live CC 78 read of its slot 1 answers from ``live[0]``, ``(days, (h, m), (h, m))`` or ``None``.
        """
        value_ids, invoke = gateway.node_get_defined_value_ids, gateway.invoke_cc_api

        def node_get_defined_value_ids(*, node_id: int, timeout_seconds: float = 5.0):
            ids = value_ids(node_id=node_id, timeout_seconds=timeout_seconds)
            return [*ids, {"commandClass": 78, "property": "numWeekDaySlots"}] if node_id == 14 else ids

        def invoke_cc_api(**kwargs):
            if (kwargs["node_id"], kwargs["command_class"]) != (14, 78):
                return invoke(**kwargs)
            if kwargs["method_name"] == "getNumSlots":
                return {"numDailyRepeatingSlots": 7}
            entry, schedule = kwargs["args"][0], live[0]
            bit = int(entry["slotId"]) - 1
            if entry["userId"] != 1 or schedule is None or not schedule[0] & (1 << bit):
                return {}
            days, (start_h, start_m), (end_h, end_m) = schedule
            minutes = (end_h * 60 + end_m) - (start_h * 60 + start_m)
            return {
                "weekdays": [lock_push_uc._WEEKDAY_BIT_TO_ZWAVE[bit]],
                "startHour": start_h,
                "startMinute": start_m,
                "durationHour": minutes // 60,
                "durationMinute": minutes % 60,
            }

        gateway.node_get_defined_value_ids = node_get_defined_value_ids
        gateway.invoke_cc_api = invoke_cc_api

    @staticmethod
    def _disable_slots(gateway: ClearFailingGateway, disabled: set[tuple[int, int]]) -> None:
        """Make the ``(node, slot)`` pairs in ``disabled`` (checked on every read) report Occupied/Disabled."""
        get_value, handle = gateway.node_get_value, gateway._handle_user_code_call

        def node_get_value(*, node_id: int, value_id: dict, timeout_seconds: float = 5.0):
            value = get_value(node_id=node_id, value_id=value_id, timeout_seconds=timeout_seconds)
            key = (node_id, int(value_id.get("propertyKey") or 0))
            return 2 if value_id.get("property") == "userIdStatus" and value == 1 and key in disabled else value

        def handle_user_code_call(*, node_id: int, method_name: str, args: list):
            response = handle(node_id=node_id, method_name=method_name, args=args)
            if method_name == "get" and (node_id, int(args[0])) in disabled and response.get("userIdStatus") == 1:
                return {**response, "userIdStatus": 2}
            return response

        gateway.node_get_value = node_get_value
        gateway._handle_user_code_call = handle_user_code_call


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


class StaleCachePushedSlotReconcileTests(PushedSlotReconcileTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheDeleteTests(DeleteTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheImportLockChangeTests(ImportLockChangeTests):
    CACHE_UPDATES_ON_SET = False
