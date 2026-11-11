"""A synced code with no import lock left becomes a manual code (issue #222).

The master code was imported from the Front Door (node 14, slot 1) and the
Back Door (node 12) was added to it, where latchpoint pushed it into slot 2.
Only the Front Door decides a synced code's PIN, active flag and schedule
(ADR 0082), so once a lock change takes it off the code (or takes it off and
adds it back, which makes it a pushed lock) nothing would ever change them
again. The code is made manual instead, and from then on goes through the
manual code paths.
"""

from __future__ import annotations

from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_added_lock_reconcile import TIMEOUT, _ReconcileTestBase
from locks.tests.test_door_code_lifecycle import _iso
from locks.tests.test_synced_code_locks import OTHER_PIN
from locks.use_cases import lock_push as lock_push_uc

KEYPAD_PIN = "5555"


class ImportLockRemovedTests(_ReconcileTestBase):
    def _remove_front(self, master: DoorCode, gateway) -> dict:
        data = self._patch(master, gateway, {"remove_lock_entity_ids": [self.FRONT]})
        master.refresh_from_db()
        return data

    def _assert_manual(self, master: DoorCode) -> None:
        master.refresh_from_db()
        self.assertEqual(master.source, DoorCode.Source.MANUAL)

    def test_removing_the_import_lock_makes_it_manual_with_an_editable_pin_and_active(self):
        master, gateway = self._master_on_both()

        data = self._remove_front(master, gateway)

        self.assertEqual(data["source"], DoorCode.Source.MANUAL)
        self.assertEqual(data["lock_entity_ids"], [self.BACK])
        self.assertEqual(master.source, DoorCode.Source.MANUAL)
        self.assertTrue(master.is_active)
        self.assertEqual(self._slots(master), {self.BACK: 2})
        self.assertEqual(self._lock_codes(gateway, 14), {})
        # The Back Door already had the code's PIN and schedule, so it's left as it is.
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._calls(gateway, "set"), [])
        event = self._updated_event(master)
        self.assertIn("source", event.metadata["updated_fields"])
        self.assertEqual(
            event.metadata["source_changed"], {"from": "synced", "to": "manual", "reason": "no_import_lock"}
        )
        self.assertEqual(event.metadata["removed_lock_entity_ids"], [self.FRONT])

        # The PIN and Active are editable now, and an edit goes out to the Back Door.
        gateway.invoke_calls.clear()
        data = self._patch(master, gateway, {"code": self.NEW_PIN})
        self.assertEqual(self._pin(master), self.NEW_PIN)
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(data["push_state"], DoorCode.PushState.PUSHED)

        self._patch(master, gateway, {"is_active": False})
        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

        self._patch(master, gateway, {"is_active": True})
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_its_schedule_is_editable_too(self):
        gateway = self._gateway()
        master = self._master(gateway)
        # The Front Door gives it a weekday schedule, so it's temporary.
        self._sync_front(gateway, days=self.WEEKDAYS)
        master.refresh_from_db()
        self.assertEqual((master.code_type, master.days_of_week), (DoorCode.CodeType.TEMPORARY, self.WEEKDAYS))
        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})
        self._remove_front(master, gateway)
        self._assert_manual(master)
        gateway.invoke_calls.clear()

        self._patch(master, gateway, {"days_of_week": self.MON_WED, "window_start": "09:00", "window_end": "17:00"})

        master.refresh_from_db()
        self.assertEqual(master.days_of_week, self.MON_WED)
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        # Monday and Wednesday from 9.
        back_schedule = [c for c in self._schedule_calls(gateway) if c[0] == 12]
        self.assertEqual(len({c[2] for c in back_schedule}), 2)
        self.assertEqual({c[3] for c in back_schedule}, {9})

    def test_later_syncs_keep_it_manual_and_import_no_copy(self):
        master, gateway = self._master_on_both()
        self._remove_front(master, gateway)
        self._patch(master, gateway, {"code": self.NEW_PIN})
        codes = DoorCode.objects.count()

        result = self._sync(gateway, self.BACK)

        row = self._slot_row(result, 2)
        self.assertEqual(row.door_code_id, master.id)
        self.assertNotIn("pin_mismatch", row.warnings)
        self.assertEqual(row.duplicate_pin_door_code_ids, [])
        self.assertEqual(result.created, 0)
        self.assertEqual(result.deactivated, 0)
        self.assertEqual(DoorCode.objects.count(), codes)
        self._assert_manual(master)
        self.assertTrue(master.is_active)
        self.assertEqual(self._pin(master), self.NEW_PIN)
        self.assertEqual(self._slots(master), {self.BACK: 2})
        # The Front Door has nothing of it any more.
        self.assertEqual(self._sync(gateway, self.FRONT).created, 0)
        self.assertEqual(DoorCode.objects.count(), codes)

        # And nothing is left for the scheduler or the reconcile to send.
        gateway.invoke_calls.clear()
        self._push_requested(gateway)
        self._push_pending(gateway)
        self.assertEqual(self._node_calls(gateway, 12), [])
        self._assert_manual(master)

    def test_a_keypad_pin_in_its_slot_is_flagged_not_taken(self):
        # The manual code rule (#166): another PIN in its own slot never becomes its PIN.
        master, gateway = self._master_on_both()
        self._remove_front(master, gateway)
        gateway._lock_codes[(12, 2)] = OTHER_PIN
        gateway._cache_codes[(12, 2)] = OTHER_PIN

        row = self._slot_row(self._sync(gateway, self.BACK), 2)

        self.assertEqual((row.action, row.door_code_id), ("skipped", master.id))
        self.assertIn("pin_mismatch", row.warnings)
        self.assertEqual(self._pin(master), self.PIN)
        self._assert_manual(master)

    def test_a_back_door_waiting_for_its_reconcile_is_cleared_and_pushed_once(self):
        # The Front Door's PIN changed and its sync flagged the Back Door, which
        # still has the old PIN when the Front Door is removed.
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        self.assertIsNotNone(self._back(master).reconcile_requested_at)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        gateway.invoke_calls.clear()

        self._remove_front(master, gateway)

        self._assert_manual(master)
        back = self._back(master)
        self.assertIsNone(back.reconcile_requested_at)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(self._calls(gateway, "clear"), [(14, [1]), (12, [2])])
        self.assertEqual(self._calls(gateway, "set"), [(12, [2, 1, self.NEW_PIN])])
        self.assertEqual((back.slot_index, back.push_state, back.last_push_error), (2, DoorCode.PushState.PUSHED, ""))

        # Nothing writes it a second time.
        gateway.invoke_calls.clear()
        self._push_requested(gateway)
        self._push_pending(gateway)
        self.assertEqual(self._node_calls(gateway, 12), [])

    def _flagged_back_door(self) -> tuple[DoorCode, object]:
        """The Front Door's PIN changed and its sync flagged the Back Door, which still has the old PIN in slot 2."""
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        self.assertIsNotNone(self._back(master).reconcile_requested_at)
        gateway.invoke_calls.clear()
        return master, gateway

    def test_a_keypad_pin_in_a_flagged_slot_is_left_alone(self):
        master, gateway = self._flagged_back_door()
        # Someone typed their own code into the Back Door's slot 2 at the keypad.
        gateway._lock_codes[(12, 2)] = KEYPAD_PIN
        gateway._cache_codes[(12, 2)] = KEYPAD_PIN

        self._remove_front(master, gateway)

        self._assert_manual(master)
        self.assertNotIn((12, [2]), self._calls(gateway, "clear"))
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: KEYPAD_PIN, 3: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.BACK: 3})
        self.assertIsNone(self._back(master).reconcile_requested_at)
        # Nothing is left to clear it later either.
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=master), [])
        gateway.invoke_calls.clear()
        self._push_pending(gateway)
        self.assertEqual(self._node_calls(gateway, 12), [])

    def test_a_flagged_slot_that_doesnt_answer_is_read_back_before_its_cleared(self):
        master, gateway = self._flagged_back_door()
        # Every try of the read back of slot 2 times out. The value cache has
        # caught up with slot 2, so the push doesn't take it for a free one.
        gateway._get_scripts[12] = [TIMEOUT] * 3
        gateway._cache_codes[(12, 2)] = self.PIN

        data = self._remove_front(master, gateway)

        self.assertEqual(data["source"], DoorCode.Source.MANUAL)
        self.assertNotIn((12, [2]), self._calls(gateway, "clear"))
        # The code went into a free slot, and slot 2 waits for a retry that reads it back first.
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN, 3: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.BACK: 3})
        [failure] = lock_push_uc.unresolved_clear_failures(door_code=master)
        self.assertEqual((failure.lock_entity_id, failure.slot_index), (self.BACK, 2))
        self.assertTrue(failure.unconfirmed)
        self.assertEqual(failure.expected_pin, self.PIN)

        self._push_pending(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 3: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.BACK: 3})
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=master), [])

    def test_a_keypad_pin_in_a_flagged_slot_that_didnt_answer_is_still_left_alone(self):
        master, gateway = self._flagged_back_door()
        gateway._get_scripts[12] = [TIMEOUT] * 3
        gateway._cache_codes[(12, 2)] = self.PIN
        self._remove_front(master, gateway)
        # Typed in at the keypad after the read that didn't answer.
        gateway._lock_codes[(12, 2)] = KEYPAD_PIN
        gateway._cache_codes[(12, 2)] = KEYPAD_PIN

        self._push_pending(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: KEYPAD_PIN, 3: self.NEW_PIN})
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=master), [])

    def test_a_back_door_whose_clear_fails_is_retried_like_a_manual_codes(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        gateway.clear_fails_on = {12}

        data = self._remove_front(master, gateway)

        self.assertEqual(data["source"], DoorCode.Source.MANUAL)
        back = self._back(master)
        self.assertIsNone(back.reconcile_requested_at)
        self.assertEqual(back.slot_index, 2)
        [failure] = [f for f in self._clear_failed_events(master) if f.lock_entity_id == self.BACK]
        self.assertEqual(failure.metadata["slot_index"], 2)
        self.assertNotIn(self.NEW_PIN, str(failure.metadata))
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

        gateway.clear_fails_on = set()
        self._push_pending(gateway)
        self._push_pending(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.BACK: 2})

    def test_an_import_lock_whose_clear_fails_is_left_to_its_retry(self):
        master, gateway = self._master_on_both()
        gateway.clear_fails_on = {14}

        data = self._remove_front(master, gateway)

        self.assertEqual(data["source"], DoorCode.Source.MANUAL)
        removing = {a["lock_entity_id"]: a["pending_removal"] for a in data["lock_slot_assignments"]}
        self.assertEqual(removing, {self.FRONT: True, self.BACK: False})
        # A Front Door sync meanwhile leaves its slot to the clear.
        row = self._slot_row(self._sync(gateway, self.FRONT), 1)
        self.assertEqual((row.action, row.door_code_id), ("skipped", master.id))
        self._assert_manual(master)
        self.assertTrue(master.is_active)

        gateway.clear_fails_on = set()
        self._push_pending(gateway)

        self.assertEqual(self._lock_codes(gateway, 14), {})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._slots(master), {self.BACK: 2})
        self._assert_manual(master)

    def test_removing_and_adding_back_the_import_lock(self):
        master, gateway = self._master_on_both()
        self._remove_front(master, gateway)
        gateway.invoke_calls.clear()

        data = self._patch(master, gateway, {"add_lock_entity_ids": [self.FRONT]})

        self.assertEqual(data["source"], DoorCode.Source.MANUAL)
        self.assertEqual(self._calls(gateway, "set"), [(14, [1, 1, self.PIN])])
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        # The Front Door's slot is latchpoint's now: a PIN typed into it isn't taken.
        self._change_front_pin(gateway, self.NEW_PIN)
        row = self._slot_row(self._sync(gateway, self.FRONT), 1)
        self.assertEqual((row.action, row.door_code_id), ("skipped", master.id))
        self.assertIn("pin_mismatch", row.warnings)
        self.assertEqual(self._pin(master), self.PIN)
        self._assert_manual(master)

    def test_adding_the_import_lock_back_while_its_removal_is_pending(self):
        master, gateway = self._master_on_both()
        gateway.clear_fails_on = {14}
        self._remove_front(master, gateway)
        self._assert_manual(master)

        data = self._patch(master, gateway, {"add_lock_entity_ids": [self.FRONT]})

        self.assertEqual(data["source"], DoorCode.Source.MANUAL)
        removing = {a["lock_entity_id"]: a["pending_removal"] for a in data["lock_slot_assignments"]}
        self.assertEqual(removing, {self.FRONT: False, self.BACK: False})
        # Its slot is still cleared and pushed again, like a manual code's.
        gateway.clear_fails_on = set()
        self._push_pending(gateway)
        self.assertEqual(list(self._lock_codes(gateway, 14).values()), [self.PIN])
        self.assertEqual(set(self._slots(master)), {self.FRONT, self.BACK})
        self.assertIsNotNone(self._slots(master)[self.FRONT])
        self._assert_manual(master)

    def test_swapping_the_import_lock_for_another_in_one_save(self):
        gateway = self._gateway()
        master = self._master(gateway)

        data = self._patch(
            master, gateway, {"add_lock_entity_ids": [self.BACK], "remove_lock_entity_ids": [self.FRONT]}
        )

        self.assertEqual(data["source"], DoorCode.Source.MANUAL)
        self.assertEqual(self._lock_codes(gateway, 14), {})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._slots(master), {self.BACK: 2})

    def test_delete_after_it_turned_manual(self):
        master, gateway = self._master_on_both()
        self._remove_front(master, gateway)
        gateway.invoke_calls.clear()

        response = self._delete(master, gateway)

        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(DoorCode.objects.filter(id=master.id).exists())
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        deleted = DoorCodeEvent.objects.filter(event_type=DoorCodeEvent.EventType.CODE_DELETED).latest("id")
        self.assertEqual(deleted.metadata["cleared_slots"], [{"lock_entity_id": self.BACK, "slot_index": 2}])

    def test_an_off_code_turns_into_an_off_manual_code(self):
        # The Front Door turned it off (its PIN was deleted there), then the Front Door is removed.
        master, gateway = self._master_on_both()
        del gateway._lock_codes[(14, 1)]
        del gateway._cache_codes[(14, 1)]
        self._sync(gateway, self.FRONT)
        self.assertEqual(self._slots(master), {self.FRONT: None, self.BACK: 2})

        self._remove_front(master, gateway)

        self._assert_manual(master)
        self.assertFalse(master.is_active)
        # Off means off its locks for a manual code, so the scheduler's inactive clear takes it off the Back Door.
        self._push_pending(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(self._slots(master), {self.BACK: None})
        # And it can be turned back on.
        self._patch(master, gateway, {"is_active": True})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

    def test_a_dated_permanent_code_turns_temporary_so_its_dates_stay_editable(self):
        gateway = self._gateway()
        master = self._master(gateway)
        end_at = self._from_now(days=1)
        DoorCode.objects.filter(id=master.id).update(end_at=end_at)
        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})

        self._remove_front(master, gateway)

        self.assertEqual((master.source, master.code_type), (DoorCode.Source.MANUAL, DoorCode.CodeType.TEMPORARY))
        self.assertEqual(master.end_at, end_at)
        self.assertEqual(self._updated_event(master).metadata["updated_fields"][-2:], ["source", "code_type"])
        later = self._from_now(days=3)
        self._patch(master, gateway, {"end_at": _iso(later)})
        self.assertEqual(DoorCode.objects.get(id=master.id).end_at, later)

    def test_removing_an_added_lock_leaves_it_synced(self):
        master, gateway = self._master_on_both()

        data = self._patch(master, gateway, {"remove_lock_entity_ids": [self.BACK]})

        self.assertEqual(data["source"], DoorCode.Source.SYNCED)
        self.assertNotIn("source_changed", self._updated_event(master).metadata)

    def test_a_code_the_front_door_let_go_of_stays_synced_while_that_lock_is_on_it(self):
        # Its Front Door row lost its slot, but lock sync made it, so it still counts.
        master, gateway = self._master_on_both()
        del gateway._lock_codes[(14, 1)]
        del gateway._cache_codes[(14, 1)]
        self._sync(gateway, self.FRONT)

        data = self._patch(master, gateway, {"add_lock_entity_ids": [self.SIDE]})

        self.assertEqual(data["source"], DoorCode.Source.SYNCED)

    def test_only_a_lock_change_makes_it_manual(self):
        # A code whose import lock went before this fix (the row was dropped
        # then): a new label leaves it as it is, a lock change makes it manual.
        master, gateway = self._master_on_both()
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.FRONT).delete()
        del gateway._lock_codes[(14, 1)]
        gateway._cache_codes.pop((14, 1), None)

        self.assertEqual(self._patch(master, gateway, {"label": "Old master"})["source"], DoorCode.Source.SYNCED)

        data = self._patch(master, gateway, {"add_lock_entity_ids": [self.FRONT]})
        self.assertEqual(data["source"], DoorCode.Source.MANUAL)
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})


class StaleCacheImportLockRemovedTests(ImportLockRemovedTests):
    """The same with the FakeGateway default, where a set doesn't reach the value cache."""

    CACHE_UPDATES_ON_SET = False
