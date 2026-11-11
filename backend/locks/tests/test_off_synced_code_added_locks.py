"""A synced code turned off at its import lock comes off the locks added to it (issue #221).

The master code was imported from the Front Door (node 14, slot 1) and the Back
Door (node 12) was added to it, where latchpoint pushed it into slot 2. When
the Front Door's slot reads empty or disabled, lock sync reads it back live
twice before it turns the code off, and only then flags the Back Door so the
reconcile takes the PIN off it (with #223's read first). A stale value cache
never turns the code off or clears anything.

Also the recovery after a refused delete of such a code: the clears it left are
retried by the scheduler, reading an added lock's slot back first, and Retry
says plainly when nothing is left to do.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_added_lock_reconcile import TIMEOUT, _ReconcileTestBase
from locks.tests.test_synced_code_locks import OTHER_PIN
from locks.use_cases import added_lock_reconcile as reconcile_uc
from locks.use_cases import lock_push as lock_push_uc

KEYPAD_PIN = "5555"
EMPTY = {"userIdStatus": 0, "userCode": ""}


class _OffTestBase(_ReconcileTestBase):
    def _delete_at_front(self, gateway) -> None:
        """Someone deletes the master PIN from Front Door slot 1."""
        del gateway._lock_codes[(14, 1)]
        del gateway._cache_codes[(14, 1)]

    def _keypad_pin_in_back_slot(self, gateway) -> None:
        """Someone programs another PIN into the master code's Back Door slot 2."""
        gateway._lock_codes[(12, 2)] = KEYPAD_PIN
        gateway._cache_codes[(12, 2)] = KEYPAD_PIN

    @staticmethod
    def _disable_in_cache_only(gateway, node: int, slot: int) -> None:
        """The value cache calls the slot Occupied/Disabled while the lock has it enabled."""
        get_value = gateway.node_get_value

        def node_get_value(*, node_id: int, value_id: dict, timeout_seconds: float = 5.0):
            value = get_value(node_id=node_id, value_id=value_id, timeout_seconds=timeout_seconds)
            key = (node_id, int(value_id.get("propertyKey") or 0))
            return 2 if value_id.get("property") == "userIdStatus" and value == 1 and key == (node, slot) else value

        gateway.node_get_value = node_get_value

    @staticmethod
    def _front_gets(gateway) -> int:
        return len([c for c in gateway.invoke_calls if c["node_id"] == 14 and c["method_name"] == "get"])

    def _off_events(self, master: DoorCode):
        return DoorCodeEvent.objects.filter(door_code=master, metadata__off_confirmed=True)

    def _retry(self, code: DoorCode, gateway):
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            return self.client.post(reverse("door-code-push", args=[code.id]), {}, format="json")


class EmptyAtImportLockTests(_OffTestBase):
    def test_a_pin_deleted_at_the_front_door_comes_off_the_back_door_once_confirmed(self):
        master, gateway = self._master_on_both()
        self._delete_at_front(gateway)

        self._sync_front(gateway)

        master.refresh_from_db()
        self.assertFalse(master.is_active)
        # Read back live twice before the code went off.
        self.assertEqual(self._front_gets(gateway), 2)
        [event] = self._off_events(master)
        self.assertEqual(event.metadata["taken_off_lock_entity_ids"], [self.BACK])
        back = self._back(master)
        self.assertIsNotNone(back.reconcile_requested_at)
        self.assertEqual(back.last_push_error, reconcile_uc.OFF_WAITING_ERROR)
        self.assertEqual(self.woken, ["push_requested_door_codes"])
        # The card says it's still being taken off the Back Door.
        self.assertEqual(master.push_state, DoorCode.PushState.PENDING)
        self.assertIn(self.BACK, master.last_push_error)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.reconcile_requested_at, back.last_push_error), (None, None, ""))
        master.refresh_from_db()
        self.assertEqual(master.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(master.last_push_error, "")
        self.assertFalse(DoorCodeEvent.objects.filter(door_code=master, metadata__action="clear_failed").exists())

        # Nothing goes back on either lock, and a Back Door sync imports nothing.
        gateway.invoke_calls.clear()
        self._push_pending(gateway)
        self.assertEqual(self._calls(gateway, "set"), [])
        result = self._sync(gateway, self.BACK)
        self.assertEqual(result.created, 0)

    def test_a_keypad_pin_in_the_back_door_slot_is_left_alone(self):
        master, gateway = self._master_on_both()
        self._keypad_pin_in_back_slot(gateway)
        self._delete_at_front(gateway)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: KEYPAD_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.reconcile_requested_at), (None, None))

    def test_a_keypad_pin_in_a_slot_from_before_0012_is_left_alone(self):
        # Nothing recorded there, but the take-off knows the code's PIN is what
        # should be in it, so another PIN isn't taken for latchpoint's (#226 review).
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        self._keypad_pin_in_back_slot(gateway)
        self._delete_at_front(gateway)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: KEYPAD_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.reconcile_requested_at), (None, None))

    def test_a_slot_from_before_0012_holding_the_pin_is_cleared(self):
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        self._delete_at_front(gateway)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

    def test_a_stale_front_cache_turns_nothing_off_and_clears_nothing(self):
        # The cache calls Front Door slot 1 Available while the PIN is still in it.
        master, gateway = self._master_on_both()
        del gateway._cache_codes[(14, 1)]

        result = self._sync_front(gateway)

        row = self._slot_row(result, 1)
        self.assertEqual((row.action, row.door_code_id), ("skipped", master.id))
        self.assertIn("slot_not_confirmed_empty", row.warnings)
        master.refresh_from_db()
        self.assertTrue(master.is_active)
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        self.assertIsNone(self._back(master).reconcile_requested_at)
        self.assertFalse(self._off_events(master).exists())
        gateway.invoke_calls.clear()
        self._push_requested(gateway)
        self._push_pending(gateway)
        self.assertEqual(self._node_calls(gateway), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

    def test_an_empty_answer_then_the_pin_isnt_confirmation(self):
        master, gateway = self._master_on_both()
        del gateway._cache_codes[(14, 1)]
        gateway._get_scripts[14] = [EMPTY, {"userIdStatus": 1, "userCode": self.PIN}]

        self._sync_front(gateway)

        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self.assertIsNone(self._back(master).reconcile_requested_at)

    def test_an_empty_answer_then_no_answer_isnt_confirmation(self):
        master, gateway = self._master_on_both()
        self._delete_at_front(gateway)
        gateway._get_scripts[14] = [EMPTY, TIMEOUT, TIMEOUT, TIMEOUT]

        result = self._sync_front(gateway)

        self.assertIn("slot_not_confirmed_empty", self._slot_row(result, 1).warnings)
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})

        # The next sync whose readbacks answer turns it off.
        self._sync_front(gateway)
        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)

    def test_an_added_lock_with_nothing_on_it_yet_is_left_as_it_is(self):
        gateway = self._gateway()
        master = self._master(gateway)
        with patch.object(lock_push_uc, "push_task_running", return_value=True):
            self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})
        self._delete_at_front(gateway)

        self._sync_front(gateway)

        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)
        back = self._back(master)
        self.assertIsNone(back.reconcile_requested_at)
        self.assertIsNone(back.slot_index)
        self.assertEqual(self._off_events(master).get().metadata["taken_off_lock_entity_ids"], [])

    def test_a_code_only_on_its_import_lock_still_goes_off_on_the_cache(self):
        gateway = self._gateway()
        master = self._master(gateway)
        self._delete_at_front(gateway)

        self._sync_front(gateway)

        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)
        self.assertEqual(self._front_gets(gateway), 0)


class DisabledAtImportLockTests(_OffTestBase):
    def test_a_slot_disabled_at_the_front_door_takes_the_pin_off_and_enabling_it_puts_it_back(self):
        master, gateway = self._master_on_both()
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)

        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertIn("taking_off_other_locks", row.warnings)
        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)
        self.assertEqual(self._front_gets(gateway), 2)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: None})

        # Enabled again at the Front Door: back on the Back Door within seconds.
        disabled.clear()
        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertIn("sent_to_other_locks", row.warnings)
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        self.assertEqual(DoorCode.objects.get(id=master.id).push_state, DoorCode.PushState.PUSHED)

    def test_a_stale_disabled_cache_turns_nothing_off(self):
        master, gateway = self._master_on_both()
        self._disable_in_cache_only(gateway, 14, 1)

        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertIn("off_change_unconfirmed", row.warnings)
        self.assertNotIn("taking_off_other_locks", row.warnings)
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self.assertIsNone(self._back(master).reconcile_requested_at)
        self._push_requested(gateway)
        self._push_pending(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

    def test_one_disabled_answer_isnt_confirmation(self):
        master, gateway = self._master_on_both()
        self._disable_in_cache_only(gateway, 14, 1)
        gateway._get_scripts[14] = [{"userIdStatus": 2, "userCode": self.PIN}]

        self._sync_front(gateway)

        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self.assertIsNone(self._back(master).reconcile_requested_at)

    def test_a_disabled_slot_with_a_new_pin_takes_the_old_one_off(self):
        master, gateway = self._master_on_both()
        self._disable_slots(gateway, {(14, 1)})
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._pin(master), self.NEW_PIN)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})


class OffCodeLeftoverTests(_OffTestBase):
    def test_a_code_turned_off_before_this_waits_until_the_front_door_confirms_it(self):
        # Turned off by a cache read before #221 with the Back Door flagged by #223: no
        # confirmation is on record, so nothing comes off until a sync confirms it.
        master, gateway = self._master_on_both()
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)
        DoorCode.objects.filter(id=master.id).update(is_active=False)
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            reconcile_requested_at=timezone.now(), last_push_error=reconcile_uc.WAITING_ERROR
        )

        self._push_requested(gateway)
        self._push_pending(gateway)

        self.assertEqual(self._node_calls(gateway), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

    def test_a_flag_set_after_the_confirmation_waits(self):
        master, gateway = self._master_on_both()
        self._delete_at_front(gateway)
        self._sync_front(gateway)
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            reconcile_requested_at=timezone.now() + timedelta(seconds=1)
        )

        outcome = reconcile_uc.reconcile_added_lock(door_code_id=master.id, lock_entity_id=self.BACK, zwavejs=gateway)

        self.assertEqual(outcome, reconcile_uc.WAITING)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

    def test_a_back_door_that_doesnt_answer_is_retried_and_never_recorded_as_a_clear_failure(self):
        master, gateway = self._master_on_both()
        self._delete_at_front(gateway)
        self._sync_front(gateway)
        gateway._get_scripts[12] = [TIMEOUT] * 3

        self._push_requested(gateway)

        back = self._back(master)
        self.assertEqual((back.slot_index, back.push_attempt_count), (2, 1))
        self.assertIsNotNone(back.reconcile_requested_at)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertFalse(DoorCodeEvent.objects.filter(door_code=master, metadata__action="clear_failed").exists())

        self._push_pending(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

    def test_retry_takes_it_off_after_the_cap(self):
        master, gateway = self._master_on_both()
        self._delete_at_front(gateway)
        self._sync_front(gateway)
        gateway.clear_fails_on.add(12)
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            push_attempt_count=lock_push_uc._push_max_attempts() - 1
        )
        self._push_requested(gateway)
        self.assertEqual(self._back(master).push_state, DoorCode.PushState.FAILED)
        self.assertEqual(DoorCode.objects.get(id=master.id).push_state, DoorCode.PushState.FAILED)
        self._push_pending(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

        gateway.clear_fails_on.clear()
        response = self._retry(master, gateway)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(DoorCode.objects.get(id=master.id).push_state, DoorCode.PushState.PUSHED)

    def test_retention_keeps_the_confirmation_while_the_back_door_is_still_flagged(self):
        master, gateway = self._master_on_both()
        self._delete_at_front(gateway)
        self._sync_front(gateway)
        event = self._off_events(master).get()
        # Flagged right before the confirmation, both long ago.
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            reconcile_requested_at=timezone.now() - timedelta(days=92)
        )

        self._run_retention(DoorCodeEvent.objects.filter(id=event.id))

        self.assertTrue(DoorCodeEvent.objects.filter(id=event.id).exists())
        DoorCodeLockAssignment.objects.filter(door_code=master).update(reconcile_requested_at=None)
        self._run_retention(DoorCodeEvent.objects.filter(id=event.id))
        self.assertFalse(DoorCodeEvent.objects.filter(id=event.id).exists())


class TakeOffRaceTests(_OffTestBase):
    """Review of PR #226: pushes and turn-ons that cross a confirmed off."""

    def _off_at_front_during_back_set(self, gateway) -> None:
        """The PIN is deleted at the Front Door and the Front Door synced while the Back Door's ``set`` is out."""

        def delete_and_sync():
            self._delete_at_front(gateway)
            self._sync(gateway, self.FRONT)

        self._before_call(gateway, node_id=12, command_class=99, method_name="set", hook=delete_and_sync)

    def test_the_first_push_to_an_added_lock_that_lands_after_the_off_is_taken_off(self):
        gateway = self._gateway()
        master = self._master(gateway)
        self._off_at_front_during_back_set(gateway)

        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})

        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._calls(gateway, "set"), [(12, [2, 1, self.PIN])])
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.reconcile_requested_at), (None, None))
        self.assertEqual(master.push_state, DoorCode.PushState.PUSHED)

    def test_a_reconcile_push_that_lands_after_the_off_is_taken_off(self):
        # Disabled, taken off, enabled again, and the PIN deleted at the Front Door
        # while the reconcile's push back onto the Back Door is out.
        master, gateway = self._master_on_both()
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)
        self._sync_front(gateway)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        disabled.clear()
        self._sync_front(gateway)
        self._off_at_front_during_back_set(gateway)
        gateway.invoke_calls.clear()

        self._push_requested(gateway)

        master.refresh_from_db()
        self.assertFalse(master.is_active)
        self.assertEqual(self._calls(gateway, "set"), [(12, [2, 1, self.PIN])])
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.reconcile_requested_at), (None, None))
        self.assertEqual(master.push_state, DoorCode.PushState.PUSHED)

    def _back_with_only_an_unconfirmed_attempt(self):
        """The master code on both doors, its Back Door push in slot 2 never confirmed."""
        gateway = self._gateway(get_responses={12: [TIMEOUT] * 20})
        master = self._master(gateway)
        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})
        gateway._get_scripts[12] = []
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: None})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        gateway.invoke_calls.clear()
        return master, gateway

    def test_an_added_lock_with_only_an_unconfirmed_push_is_flagged(self):
        # M5.
        master, gateway = self._back_with_only_an_unconfirmed_attempt()
        self._delete_at_front(gateway)

        self._sync_front(gateway)

        self.assertIsNotNone(self._back(master).reconcile_requested_at)
        self.assertEqual(self._off_events(master).get().metadata["taken_off_lock_entity_ids"], [self.BACK])

    def test_the_take_off_clears_an_unconfirmed_slot_holding_the_current_pin(self):
        # M10: the push would adopt it if the code were on, but nothing will now.
        master, gateway = self._back_with_only_an_unconfirmed_attempt()
        self._delete_at_front(gateway)
        self._sync_front(gateway)

        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=master), [])

    def test_a_code_turned_back_on_while_its_taken_off_goes_back_on(self):
        # M13: enabled again at the Front Door right as the take-off clears the Back Door.
        master, gateway = self._master_on_both()
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)
        self._sync_front(gateway)

        def enable_and_sync():
            disabled.clear()
            self._sync(gateway, self.FRONT)

        self._before_call(gateway, node_id=12, command_class=99, method_name="clear", hook=enable_and_sync)

        self._push_requested(gateway)

        master.refresh_from_db()
        self.assertTrue(master.is_active)
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.reconcile_requested_at), (2, None))
        self.assertEqual(master.push_state, DoorCode.PushState.PUSHED)


class TakeOffApiTests(_OffTestBase):
    def _back_entry(self, master: DoorCode) -> dict:
        response = self.client.get(reverse("door-code-detail", args=[master.id]))
        self.assertEqual(response.status_code, 200, response.content)
        return {a["lock_entity_id"]: a for a in response.json()["data"]["lock_slot_assignments"]}

    def test_the_api_says_which_lock_its_still_coming_off(self):
        master, gateway = self._master_on_both()
        self._delete_at_front(gateway)
        self._sync_front(gateway)

        locks = self._back_entry(master)
        self.assertTrue(locks[self.BACK]["taking_pin_off"])
        self.assertEqual(locks[self.BACK]["last_push_error"], reconcile_uc.OFF_WAITING_ERROR)
        self.assertFalse(locks[self.FRONT]["taking_pin_off"])

        self._push_requested(gateway)

        self.assertFalse(self._back_entry(master)[self.BACK]["taking_pin_off"])

    def test_a_lock_being_dropped_is_its_clears_not_the_take_offs(self):
        master, gateway = self._master_on_both()
        self._delete_at_front(gateway)
        self._sync_front(gateway)
        lock_push_uc.record_clear_failure(
            door_code=master, lock_entity_id=self.BACK, slot_index=2, exc=TIMEOUT, expected_pin=self.PIN, removing=True
        )
        code = DoorCode.objects.get(id=master.id)
        failures = lock_push_uc.unresolved_clear_failures(door_code=code)
        assignments = list(DoorCodeLockAssignment.objects.filter(door_code=code))

        self.assertEqual(lock_push_uc._locks_taking_pin_off(code=code, assignments=assignments, failures=failures), [])
        self.assertFalse(self._back_entry(master)[self.BACK]["taking_pin_off"])


class RefusedDeleteRecoveryTests(_OffTestBase):
    """Part two of issue #221: a delete refused because the Back Door didn't answer."""

    def test_the_scheduler_takes_the_pin_off_once_the_back_door_answers_then_delete_finishes(self):
        master, gateway = self._master_on_both()
        gateway._get_scripts[12] = [TIMEOUT] * 20

        response = self._delete(master, gateway)

        self.assertEqual(response.status_code, 502, response.content)
        self.assertIn("wasn't deleted and is now off", response.json()["error"]["message"])
        self.assertEqual(self._lock_codes(gateway, 14), {})
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        [failure] = lock_push_uc.unresolved_clear_failures(door_code=master)
        self.assertEqual((failure.lock_entity_id, failure.slot_index, failure.unconfirmed), (self.BACK, 2, True))
        # Retry has something to do while it's outstanding.
        self.assertEqual(self._retry(master, gateway).status_code, 200)

        # Nothing else needed: the scheduler reads it back and clears it once it answers.
        gateway._get_scripts[12] = []
        self._push_pending(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=master), [])
        response = self._retry(master, gateway)
        self.assertEqual(response.status_code, 409, response.content)
        message = response.json()["error"]["message"]
        self.assertIn("nothing is left to clear", message)
        self.assertIn("delete it again", message)
        self.assertEqual(self._delete(master, gateway).status_code, 204)

    def test_a_keypad_pin_typed_into_the_back_door_slot_meanwhile_is_left_alone(self):
        master, gateway = self._master_on_both()
        gateway._get_scripts[12] = [TIMEOUT] * 20
        self.assertEqual(self._delete(master, gateway).status_code, 502)
        gateway._get_scripts[12] = []
        self._keypad_pin_in_back_slot(gateway)

        self._push_pending(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(14, [1])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: KEYPAD_PIN})
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=master), [])
        self.assertEqual(self._delete(master, gateway).status_code, 204)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: KEYPAD_PIN})


# The tests above again with the FakeGateway default, where a set doesn't reach
# the value cache, so every sync after a push sees the pushed slot as Available.
class StaleCacheEmptyAtImportLockTests(EmptyAtImportLockTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheDisabledAtImportLockTests(DisabledAtImportLockTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheOffCodeLeftoverTests(OffCodeLeftoverTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheRefusedDeleteRecoveryTests(RefusedDeleteRecoveryTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheTakeOffRaceTests(TakeOffRaceTests):
    CACHE_UPDATES_ON_SET = False
