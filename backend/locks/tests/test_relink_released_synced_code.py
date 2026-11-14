"""An undated synced code lock sync let go of comes back when its PIN is typed in again (issue #233).

The master code was imported from the Front Door (node 14, slot 1). Someone
deletes its PIN at the keypad, a Front Door sync reads the slot empty, turns the
code off and lets go of the slot. Lock sync only finds a code by its slot, so
before this the same PIN typed in again came in as a new "Slot N" code and the
old one stayed off for good. Now a sync matches an untracked slot holding a
readable PIN back to the one released code with that PIN, and turns it back on
from the slot like any synced code's, putting the PIN back on the locks added
to it. No match, more than one, or a lock that hides its codes imports the slot
as before.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_off_synced_code_added_locks import _OffTestBase
from locks.tests.test_synced_code_locks import OTHER_PIN
from locks.use_cases import added_lock_reconcile as reconcile_uc
from locks.use_cases import lock_config_sync as lock_config_sync_uc


class _RelinkTestBase(_OffTestBase):
    def _released(self, gateway=None) -> tuple[DoorCode, object]:
        """The master code, only on the Front Door, after a sync found its PIN deleted there and let go of the slot."""
        gateway = gateway or self._gateway()
        master = self._master(gateway)
        return self._release_front(master, gateway), gateway

    def _release_front(self, master: DoorCode, gateway) -> DoorCode:
        self._delete_at_front(gateway)
        self._sync_front(gateway)
        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertIsNone(self._slots(master)[self.FRONT])
        gateway.invoke_calls.clear()
        return master

    def _released_on_both(self) -> tuple[DoorCode, object]:
        """The same with the Back Door added to it, once the reconcile took the PIN off the Back Door (#221)."""
        master, gateway = self._master_on_both()
        master = self._release_front(master, gateway)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: None, self.BACK: None})
        gateway.invoke_calls.clear()
        return master, gateway

    def _type_at_front(self, gateway, slot: int, pin: str | None = None, *, on_lock: bool = True) -> None:
        """Someone types ``pin`` (the master PIN by default) into Front Door slot ``slot``.

        ``on_lock=False`` only puts it in the value cache, ie a stale cache.
        """
        gateway._cache_codes[(14, slot)] = pin or self.PIN
        if on_lock:
            gateway._lock_codes[(14, slot)] = pin or self.PIN

    def _front_codes(self) -> dict[int, int | None]:
        """Door code id -> its Front Door slot."""
        return dict(
            DoorCodeLockAssignment.objects.filter(lock_entity_id=self.FRONT).values_list("door_code_id", "slot_index")
        )

    def _assert_imported_as_new(self, master: DoorCode, result, slot: int) -> None:
        row = self._slot_row(result, slot)
        self.assertEqual(row.action, "created")
        self.assertNotEqual(row.door_code_id, master.id)
        self.assertNotIn("relinked", row.warnings)
        self.assertEqual(DoorCode.objects.get(id=row.door_code_id).label, f"Slot {slot}")
        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertIsNone(self._slots(master).get(self.FRONT))


class RelinkTests(_RelinkTestBase):
    def _assert_relinked(self, slot: int) -> None:
        master, gateway = self._released()
        codes_before = DoorCode.objects.count()
        self._type_at_front(gateway, slot)

        result = self._sync_front(gateway)

        row = self._slot_row(result, slot)
        self.assertEqual((row.action, row.door_code_id), ("updated", master.id))
        self.assertIn("relinked", row.warnings)
        self.assertEqual((result.created, result.updated), (0, 1))
        self.assertEqual(DoorCode.objects.count(), codes_before)
        self.assertFalse(DoorCode.objects.filter(label=f"Slot {slot}", lock_assignments__lock_entity_id=self.FRONT))
        master.refresh_from_db()
        self.assertTrue(master.is_active)
        self.assertEqual(master.source, DoorCode.Source.SYNCED)
        self.assertEqual(master.label, "Master")
        self.assertEqual(master.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(self._slots(master), {self.FRONT: slot})
        front = DoorCodeLockAssignment.objects.get(door_code=master, lock_entity_id=self.FRONT)
        self.assertEqual((front.push_state, front.last_push_attempt_at), (DoorCode.PushState.PUSHED, None))
        event = DoorCodeEvent.objects.filter(door_code=master, event_type=DoorCodeEvent.EventType.CODE_SYNCED).latest(
            "id"
        )
        self.assertEqual(
            (event.metadata["slot_index"], event.metadata["action"], event.metadata.get("relinked")),
            (slot, "updated", True),
        )
        # Only on the Front Door, so it goes by the cache like any import, and nothing is written.
        self.assertEqual(self._front_gets(gateway), 0)
        self.assertEqual(self._node_calls(gateway, 14), [])

        # It's the code's slot from now on.
        result = self._sync_front(gateway)
        row = self._slot_row(result, slot)
        self.assertEqual((row.action, row.door_code_id, result.created), ("unchanged", master.id, 0))
        self.assertNotIn("relinked", row.warnings)
        self.assertEqual(self._slots(master), {self.FRONT: slot})

        # And deleting it at the keypad again turns it off again, and typing it in brings it back again.
        del gateway._lock_codes[(14, slot)], gateway._cache_codes[(14, slot)]
        self._sync_front(gateway)
        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)
        self._type_at_front(gateway, 4)
        self.assertEqual(self._sync_front(gateway).created, 0)
        self.assertEqual(self._slots(master), {self.FRONT: 4})
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)

    def test_the_pin_typed_into_another_slot_brings_the_code_back(self):
        self._assert_relinked(3)

    def test_the_pin_typed_into_its_old_slot_brings_the_code_back(self):
        self._assert_relinked(1)

    def test_a_disabled_slot_is_matched_back_and_the_code_stays_off(self):
        master, gateway = self._released()
        self._type_at_front(gateway, 3)
        self._disable_slots(gateway, {(14, 3)})

        result = self._sync_front(gateway)

        row = self._slot_row(result, 3)
        self.assertEqual((row.door_code_id, result.created), (master.id, 0))
        self.assertIn("relinked", row.warnings)
        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._slots(master), {self.FRONT: 3})

    def test_the_schedule_on_the_slot_is_taken(self):
        master, gateway = self._released()
        self._type_at_front(gateway, 1)

        self._sync_front(gateway, days=self.WEEKDAYS)

        master.refresh_from_db()
        self.assertTrue(master.is_active)
        self.assertEqual((master.days_of_week, master.code_type), (self.WEEKDAYS, DoorCode.CodeType.TEMPORARY))

    def test_a_dry_run_shows_it_and_changes_nothing(self):
        master, gateway = self._released()
        self._type_at_front(gateway, 3)

        with transaction.atomic():
            result = lock_config_sync_uc.sync_lock_config(
                lock_entity_id=self.FRONT, target_user=self.user, actor_user=self.user, zwavejs=gateway, dry_run=True
            )
            transaction.set_rollback(True)

        row = self._slot_row(result, 3)
        self.assertEqual((row.door_code_id, result.created), (master.id, 0))
        self.assertIn("relinked", row.warnings)
        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._slots(master), {self.FRONT: None})


class NoRelinkTests(_RelinkTestBase):
    """Anything but exactly one released code with the PIN imports the slot as before."""

    def test_two_released_codes_with_the_pin_import_a_new_code(self):
        master, gateway = self._released()
        twin = self._code(source=DoorCode.Source.SYNCED, is_active=False, slots={self.FRONT: None}, label="Twin")
        self._type_at_front(gateway, 3)

        result = self._sync_front(gateway)

        self._assert_imported_as_new(master, result, 3)
        twin.refresh_from_db()
        self.assertFalse(twin.is_active)
        self.assertEqual(self._slots(twin), {self.FRONT: None})

    def test_a_lock_that_hides_its_codes_imports_a_new_code(self):
        master, gateway = self._released()
        self._mask_reads(gateway, node=14)
        self._type_at_front(gateway, 3)

        result = self._sync_front(gateway)

        self._assert_imported_as_new(master, result, 3)
        self.assertFalse(self._slot_row(result, 3).pin_known)

    def test_the_pin_in_two_slots_imports_both(self):
        master, gateway = self._released()
        self._type_at_front(gateway, 3)
        self._type_at_front(gateway, 4)

        result = self._sync_front(gateway)

        self._assert_imported_as_new(master, result, 3)
        self._assert_imported_as_new(master, result, 4)

    def test_another_code_waiting_to_go_on_the_lock_with_the_pin_imports_a_new_code(self):
        # An active manual code with the PIN, its push to the Front Door still queued (#188).
        master, gateway = self._released()
        other = self._code(slots={self.FRONT: None}, label="Manual")
        self._type_at_front(gateway, 3)

        result = self._sync_front(gateway)

        self._assert_imported_as_new(master, result, 3)
        self.assertIn(other.id, self._slot_row(result, 3).duplicate_pin_door_code_ids)

    def test_another_pin_imports_a_new_code(self):
        master, gateway = self._released()
        self._type_at_front(gateway, 3, OTHER_PIN)

        self._assert_imported_as_new(master, self._sync_front(gateway), 3)

    def test_a_code_with_dates_imports_a_new_code(self):
        # ADR-0109: one with an end date can be turned on from latchpoint.
        master, gateway = self._released()
        DoorCode.objects.filter(id=master.id).update(end_at=timezone.now() + timedelta(days=30))
        self._type_at_front(gateway, 3)

        self._assert_imported_as_new(master, self._sync_front(gateway), 3)

    def test_a_code_whose_delete_was_refused_imports_a_new_code(self):
        master, gateway = self._released()
        DoorCodeEvent.objects.create(
            door_code=master,
            user=self.user,
            event_type=DoorCodeEvent.EventType.CODE_UPDATED,
            metadata={"updated_fields": ["is_active"], "reason": "delete_refused"},
        )
        self._type_at_front(gateway, 3)

        self._assert_imported_as_new(master, self._sync_front(gateway), 3)

    def test_a_code_released_on_another_lock_isnt_matched_here(self):
        master, gateway = self._released()
        self._type_at_front(gateway, 3)
        DoorCodeLockAssignment.objects.filter(door_code=master).update(lock_entity_id=self.SIDE)

        result = self._sync_front(gateway)

        self.assertEqual(self._slot_row(result, 3).action, "created")
        self.assertEqual(self._slots(master), {self.SIDE: None})

    def test_a_code_whose_import_lock_was_removed_is_manual_and_imports_a_new_code(self):
        # #225: with the Front Door taken off it, no lock decides its PIN, so it's a manual code.
        master, gateway = self._released_on_both()
        self._patch(master, gateway, {"remove_lock_entity_ids": [self.FRONT]})
        master.refresh_from_db()
        self.assertEqual(master.source, DoorCode.Source.MANUAL)
        self._type_at_front(gateway, 3)

        result = self._sync_front(gateway)

        row = self._slot_row(result, 3)
        self.assertEqual(row.action, "created")
        self.assertNotEqual(row.door_code_id, master.id)
        self.assertNotIn(self.FRONT, self._slots(master))

    def test_a_lock_added_before_push_requested_at_was_stamped_makes_it_ambiguous(self):
        # A Back Door row with nothing on it looks like a second import lock.
        master, gateway = self._released()
        DoorCodeLockAssignment.objects.create(door_code=master, lock_entity_id=self.BACK)
        self._type_at_front(gateway, 3)

        self._assert_imported_as_new(master, self._sync_front(gateway), 3)


class AddedLockTests(_RelinkTestBase):
    """A code matched back gets its PIN back on the locks added to it, and a take-off still waiting stops."""

    def test_the_pin_goes_back_on_the_added_lock(self):
        master, gateway = self._released_on_both()
        self._type_at_front(gateway, 3)

        result = self._sync_front(gateway)

        row = self._slot_row(result, 3)
        self.assertEqual((row.action, row.door_code_id, result.created), ("updated", master.id, 0))
        self.assertIn("relinked", row.warnings)
        self.assertIn("sent_to_other_locks", row.warnings)
        # On another lock too, so the PIN was read back live first.
        self.assertEqual(self._front_gets(gateway), 1)
        master.refresh_from_db()
        self.assertTrue(master.is_active)
        back = self._back(master)
        self.assertIsNotNone(back.reconcile_requested_at)
        self.assertEqual(back.last_push_error, reconcile_uc.WAITING_ERROR)
        self.assertEqual(self.woken, ["push_requested_door_codes"])

        self._push_requested(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 3, self.BACK: 2})
        back = self._back(master)
        self.assertIsNone(back.reconcile_requested_at)
        master.refresh_from_db()
        self.assertEqual((master.push_state, master.last_push_error), (DoorCode.PushState.PUSHED, ""))

    def test_a_take_off_still_waiting_stops_and_the_pin_stays_on_the_added_lock(self):
        # #226: the Back Door is flagged to have the PIN taken off, but the reconcile hasn't run yet.
        master, gateway = self._master_on_both()
        master = self._release_front(master, gateway)
        back = self._back(master)
        self.assertEqual(back.last_push_error, reconcile_uc.OFF_WAITING_ERROR)
        self._type_at_front(gateway, 3)

        self._sync_front(gateway)

        master.refresh_from_db()
        self.assertTrue(master.is_active)
        back = self._back(master)
        self.assertIsNotNone(back.reconcile_requested_at)
        self.assertEqual(back.last_push_error, reconcile_uc.WAITING_ERROR)
        self.assertFalse(DoorCodeLockAssignment.objects.filter(id=back.id).filter(reconcile_uc.off_clear_q()).exists())

        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 3, self.BACK: 2})
        self.assertIsNone(self._back(master).reconcile_requested_at)

    def test_a_take_off_failed_at_the_cap_is_rearmed(self):
        master, gateway = self._master_on_both()
        master = self._release_front(master, gateway)
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            push_state=DoorCode.PushState.FAILED, push_attempt_count=5
        )
        self._type_at_front(gateway, 3)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.push_state), (2, DoorCode.PushState.PUSHED))

    def test_a_stale_cache_matches_nothing_and_imports_nothing(self):
        # The cache has the PIN in Front Door slot 3, but the lock doesn't.
        master, gateway = self._released_on_both()
        self._type_at_front(gateway, 3, on_lock=False)

        result = self._sync_front(gateway)

        row = self._slot_row(result, 3)
        self.assertEqual((row.action, row.door_code_id), ("skipped", master.id))
        self.assertIn("relink_not_confirmed", row.warnings)
        self.assertEqual(result.created, 0)
        self.assertEqual(self._front_codes(), {master.id: None})
        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertIsNone(self._back(master).reconcile_requested_at)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

        # Once the lock has it, the next sync matches it back.
        gateway._lock_codes[(14, 3)] = self.PIN
        self._sync_front(gateway)
        master.refresh_from_db()
        self.assertTrue(master.is_active)
        self.assertEqual(self._slots(master)[self.FRONT], 3)

    def test_a_held_pin_on_the_added_lock_fails_it_there(self):
        # #188: meanwhile someone's code with the PIN took a Back Door slot.
        master, gateway = self._released_on_both()
        self._code(slots={self.BACK: 3}, label="Manual")
        gateway._lock_codes[(12, 3)] = gateway._cache_codes[(12, 3)] = self.PIN
        self._type_at_front(gateway, 3)

        result = self._sync_front(gateway)

        row = self._slot_row(result, 3)
        self.assertEqual(row.door_code_id, master.id)
        self.assertIn("pin_held_on_other_lock", row.warnings)
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 3: self.PIN})
        back = self._back(master)
        self.assertEqual(back.push_state, DoorCode.PushState.FAILED)
        # By label, since the error masks an id long enough to pass for a PIN.
        self.assertIn("in slot 3 as door code", back.last_push_error)
        self.assertIn('("Manual")', back.last_push_error)
