"""A new PIN or schedule lock sync takes from the Front Door goes on to the added Back Door (issue #220).

The master code was imported from the Front Door (node 14, slot 1) and the
Back Door (node 12) was added to it, where latchpoint pushed it into slot 2.
Lock sync of the Front Door only flags the Back Door; the queued push task's
reconcile (``locks.use_cases.added_lock_reconcile``) brings it in line,
reading the slot live and comparing it with what latchpoint last wrote there.
"""

from __future__ import annotations

from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse
from integrations_zwavejs.manager import ZwavejsCommandError

from alarm.crypto import SettingsEncryption
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_synced_code_locks import OTHER_PIN, _SyncedLocksTestBase
from locks.use_cases import added_lock_reconcile as reconcile_uc
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_config_sync as lock_config_sync_uc
from locks.use_cases import lock_push as lock_push_uc

TIMEOUT = ZwavejsCommandError("driver TimeoutError after 5.0s")


class _ReconcileTestBase(_SyncedLocksTestBase):
    NEW_PIN = "8642"
    LATEST_PIN = "1357"
    WEEKDAYS = 0b0011111  # Mon-Fri
    MON_WED = 0b0000101

    def _pin(self, code: DoorCode) -> str | None:
        code.refresh_from_db()
        return SettingsEncryption.get().decrypt(code.encrypted_pin) if code.encrypted_pin else None

    def _back(self, master: DoorCode) -> DoorCodeLockAssignment:
        return DoorCodeLockAssignment.objects.get(door_code=master, lock_entity_id=self.BACK)

    def _change_front_pin(self, gateway, pin: str, *, on_lock: bool = True) -> None:
        """Someone programs ``pin`` into Front Door slot 1. ``on_lock=False`` only changes the value cache."""
        gateway._cache_codes[(14, 1)] = pin
        if on_lock:
            gateway._lock_codes[(14, 1)] = pin

    def _sync_front(self, gateway, *, days: int | None = None, start: str = "08:00:00"):
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

    def _push_requested(self, gateway) -> int:
        from locks.tasks import push_requested_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            return push_requested_door_codes()

    def _node_calls(self, gateway, node_id: int = 12) -> list[dict]:
        """Every write to the node: CC 99 sets and clears, CC 78 schedules."""
        writes = {"set", "clear", "setDailyRepeatingSchedule"}
        return [c for c in gateway.invoke_calls if c["node_id"] == node_id and c["method_name"] in writes]

    @staticmethod
    def _schedule_calls(gateway) -> list[tuple[int, int, int, int]]:
        """``(node, userId, weekday, startHour)`` for every CC 78 ``setDailyRepeatingSchedule``."""
        return [
            (c["node_id"], c["args"][0]["userId"], c["args"][1]["weekdays"][0], c["args"][1]["startHour"])
            for c in gateway.invoke_calls
            if c["command_class"] == 78 and c["method_name"] == "setDailyRepeatingSchedule"
        ]

    def _clear_failed_events(self, code: DoorCode):
        return DoorCodeEvent.objects.filter(door_code=code, metadata__action="clear_failed")

    def _delete(self, code: DoorCode, gateway):
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            return self.client.delete(
                reverse("door-code-detail", args=[code.id]), {"reauth_password": "pass"}, format="json"
            )

    @staticmethod
    def _before_call(gateway, *, node_id: int, command_class: int, method_name: str, hook) -> None:
        """Run ``hook()`` once, right before the first matching ``invoke_cc_api`` call goes out."""
        invoke = gateway.invoke_cc_api
        fired: list[bool] = []

        def invoke_cc_api(**kwargs):
            key = (kwargs["node_id"], kwargs["command_class"], kwargs["method_name"])
            if key == (node_id, command_class, method_name) and not fired:
                fired.append(True)
                hook()
            return invoke(**kwargs)

        gateway.invoke_cc_api = invoke_cc_api

    @staticmethod
    def _mask_reads(gateway, *, node: int) -> None:
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
    def _disable_slots(gateway, disabled: set[tuple[int, int]]) -> None:
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

    @staticmethod
    def _front_schedule_from_cache(gateway, live: list) -> None:
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
            _days, (start_h, start_m), (end_h, end_m) = schedule
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


class PinChangeTests(_ReconcileTestBase):
    def test_a_new_pin_goes_on_to_the_added_lock_and_the_old_one_comes_off_it(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)

        result = self._sync_front(gateway)

        row = self._slot_row(result, 1)
        self.assertEqual((row.action, row.door_code_id), ("updated", master.id))
        self.assertIn("sent_to_other_locks", row.warnings)
        self.assertEqual(self._pin(master), self.NEW_PIN)
        # The sync only flags the Back Door; nothing goes to it while the sync holds the Front Door.
        self.assertEqual(self._node_calls(gateway), [])
        back = self._back(master)
        self.assertIsNotNone(back.reconcile_requested_at)
        self.assertEqual((back.slot_index, back.push_state), (2, DoorCode.PushState.PENDING))
        self.assertEqual(self.woken, ["push_requested_door_codes"])
        master.refresh_from_db()
        self.assertEqual(master.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(master.last_push_error, f"{self.BACK}: {reconcile_uc.WAITING_ERROR}")
        self.assertFalse(self._clear_failed_events(master).exists())
        synced = DoorCodeEvent.objects.filter(door_code=master, lock_entity_id=self.FRONT).latest("id")
        self.assertEqual(synced.metadata["sent_to_lock_entity_ids"], [self.BACK])

        self._push_requested(gateway)

        # The old PIN is cleared off slot 2 and the new one goes in its place.
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._calls(gateway, "set"), [(12, [2, 1, self.NEW_PIN])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(self._lock_codes(gateway, 14), {1: self.NEW_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.reconcile_requested_at), (2, None))
        self.assertEqual(SettingsEncryption.get().decrypt(back.written_pin), self.NEW_PIN)
        master.refresh_from_db()
        self.assertEqual((master.push_state, master.source), (DoorCode.PushState.PUSHED, DoorCode.Source.SYNCED))
        self.assertFalse(self._clear_failed_events(master).exists())

        # A Back Door sync no longer finds another PIN in the code's slot.
        row = self._slot_row(self._sync(gateway, self.BACK), 2)
        self.assertEqual(row.door_code_id, master.id)
        self.assertNotIn("pin_mismatch", row.warnings)
        self.assertEqual(self._pin(master), self.NEW_PIN)

    def test_the_task_is_woken_once_the_sync_commits(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)

        with patch("scheduler.runner.wake_task") as wake, patch("alarm.dispatcher.notify_entities_changed"):
            with self.captureOnCommitCallbacks() as callbacks:
                self._sync(gateway, self.FRONT)
                self.assertEqual(wake.call_count, 0)
            self.assertEqual(wake.call_count, 0)
            for callback in callbacks:
                callback()
        self.assertIn("push_requested_door_codes", [call.args[0] for call in wake.call_args_list])

    def test_a_back_door_sync_leaves_a_flagged_slot_to_the_reconcile(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)

        result = self._sync(gateway, self.BACK)

        self.assertEqual(self._back(master).push_state, DoorCode.PushState.PENDING)
        rows = [row for row in result.slots if row.door_code_id == master.id]
        self.assertTrue(all("update_pending" in row.warnings for row in rows), rows)
        self.assertEqual(self._node_calls(gateway), [])

    def test_a_front_door_that_masks_its_codes_flags_nothing(self):
        master, gateway = self._master_on_both()
        gateway._cache_codes[(14, 1)] = "****"

        result = self._sync_front(gateway)

        self.assertNotIn("sent_to_other_locks", self._slot_row(result, 1).warnings)
        self.assertEqual(self._pin(master), self.PIN)
        self.assertIsNone(self._back(master).reconcile_requested_at)
        self._push_requested(gateway)
        self._push_pending(gateway)
        self.assertEqual(self._node_calls(gateway), [])

    def test_a_new_pin_only_the_value_cache_has_is_not_taken_or_sent(self):
        # A stale or dropped write in Z-Wave JS's cache: the lock itself still has the old PIN.
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN, on_lock=False)

        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertIn("pin_change_unconfirmed", row.warnings)
        self.assertNotIn("sent_to_other_locks", row.warnings)
        self.assertEqual(self._pin(master), self.PIN)
        self.assertIsNone(self._back(master).reconcile_requested_at)

        # Once the lock really has it, the next sync takes it and it goes on.
        self._change_front_pin(gateway, self.NEW_PIN)
        self.assertIn("sent_to_other_locks", self._slot_row(self._sync_front(gateway), 1).warnings)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_a_readback_that_doesnt_answer_keeps_the_old_pin(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        gateway._get_scripts[14] = [TIMEOUT] * 3

        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertIn("pin_change_unconfirmed", row.warnings)
        self.assertEqual(self._pin(master), self.PIN)
        self.assertIsNone(self._back(master).reconcile_requested_at)

    def test_the_slot_already_holding_the_new_pin_is_kept(self):
        # Review 2, item 1: the slot's contents are compared with the code's PIN first.
        master, gateway = self._master_on_both()
        gateway._lock_codes[(12, 2)] = gateway._cache_codes[(12, 2)] = self.NEW_PIN
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)

        self._push_requested(gateway)

        self.assertEqual(self._node_calls(gateway), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.push_state, back.reconcile_requested_at), (2, "pushed", None))
        self.assertEqual(SettingsEncryption.get().decrypt(back.written_pin), self.NEW_PIN)

    def test_a_delete_clears_a_slot_already_holding_the_new_pin(self):
        master, gateway = self._master_on_both()
        gateway._lock_codes[(12, 2)] = gateway._cache_codes[(12, 2)] = self.NEW_PIN
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)

        response = self._delete(master, gateway)

        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertEqual(self._lock_codes(gateway, 14), {})

    def test_a_delete_clears_the_old_pin_latchpoint_wrote_before_its_reconcile(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)

        response = self._delete(master, gateway)

        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

    def test_a_slot_holding_a_pin_latchpoint_never_wrote_is_let_go_not_cleared(self):
        # Someone typed another PIN into the Back Door's slot 2 (the pin_mismatch case).
        master, gateway = self._master_on_both()
        gateway._lock_codes[(12, 2)] = gateway._cache_codes[(12, 2)] = "5555"
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)

        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: "5555", 3: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 3})

    def test_a_delete_leaves_a_pin_latchpoint_never_wrote(self):
        master, gateway = self._master_on_both()
        gateway._lock_codes[(12, 2)] = gateway._cache_codes[(12, 2)] = "5555"

        response = self._delete(master, gateway)

        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: "5555"})

    def test_a_back_door_that_masks_its_codes_still_gets_the_old_pin_cleared(self):
        master, gateway = self._master_on_both()
        self._mask_reads(gateway, node=12)
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)

        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def _pushed_before_0012(self, master: DoorCode) -> None:
        """The Back Door was added and pushed by #219, before migration 0012 recorded what a push wrote."""
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            written_pin=None, written_schedule=None
        )

    def test_a_slot_pushed_before_0012_has_the_old_pin_cleared_when_the_pin_changes(self):
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)

        # The sync records the code's PIN and schedule from before the change as what the push wrote.
        back = self._back(master)
        self.assertEqual(SettingsEncryption.get().decrypt(back.written_pin), self.PIN)
        self.assertEqual(back.written_schedule, "")

        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._calls(gateway, "set"), [(12, [2, 1, self.NEW_PIN])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})

    def test_a_masked_slot_pushed_before_0012_has_the_old_pin_cleared_too(self):
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        self._mask_reads(gateway, node=12)
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_a_keypad_pin_in_a_slot_pushed_before_0012_is_still_let_go(self):
        # The old PIN is what's recorded, so a third PIN there is still someone else's.
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        gateway._lock_codes[(12, 2)] = gateway._cache_codes[(12, 2)] = "5555"
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: "5555", 3: self.NEW_PIN})

    def test_a_slotless_or_imported_row_stays_unknown(self):
        master, gateway = self._master_on_both()
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            written_pin=None, written_schedule=None, last_push_attempt_at=None
        )
        self._change_front_pin(gateway, self.NEW_PIN)

        reconcile_uc.flag_added_locks(
            door_code=DoorCode.objects.get(id=master.id),
            import_lock_entity_id=self.FRONT,
            previous_pin=self.PIN,
            previous_schedule="",
        )

        back = self._back(master)
        self.assertEqual((back.written_pin, back.written_schedule), (None, None))

    def test_an_unconfirmed_push_to_the_added_lock_has_its_old_pin_cleared(self):
        # Every readback on the Back Door times out, so the PIN is only on record as an attempt in slot 2.
        gateway = self._gateway(get_responses={12: [TIMEOUT] * 3})
        master = self._master(gateway)
        self._patch(master, gateway, {"add_lock_entity_ids": [self.BACK]})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: None})
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        gateway.invoke_calls.clear()

        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})


class RaceTests(_ReconcileTestBase):
    """Lock sync changes the code again while the Back Door's reconcile is running."""

    def _change_twice_during_the_push(self, *, after_marker: bool) -> None:
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)

        def change_again():
            self._change_front_pin(gateway, self.LATEST_PIN)
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
                self._push_requested(gateway)
        else:
            self._before_call(gateway, node_id=12, command_class=99, method_name="set", hook=change_again)
            self._push_requested(gateway)

        self.assertEqual(self._pin(master), self.LATEST_PIN)
        # The push in flight wrote the PIN it read, and the reconcile went again for the newer one.
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.LATEST_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.push_state, back.reconcile_requested_at), (2, "pushed", None))
        self.assertEqual(SettingsEncryption.get().decrypt(back.written_pin), self.LATEST_PIN)
        self.assertEqual(DoorCode.objects.get(id=master.id).push_state, DoorCode.PushState.PUSHED)

    def test_a_pin_change_landing_before_the_push_writes_ends_with_the_newest_pin(self):
        self._change_twice_during_the_push(after_marker=False)

    def test_a_pin_change_landing_after_the_push_wrote_ends_with_the_newest_pin(self):
        self._change_twice_during_the_push(after_marker=True)

    def test_a_push_that_fails_after_its_set_while_the_pin_changes_leaves_nothing_behind(self):
        # Review 3, item 3: the attempt is on record with the PIN it sent, which isn't the code's any more.
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)

        def change_and_stop_answering():
            self._change_front_pin(gateway, self.LATEST_PIN)
            self._sync_front(gateway)
            gateway._get_scripts[12] = [TIMEOUT] * 3

        self._before_call(gateway, node_id=12, command_class=99, method_name="set", hook=change_and_stop_answering)
        self._push_requested(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertIsNone(self._back(master).slot_index)
        self.assertIsNotNone(self._back(master).reconcile_requested_at)

        self._push_pending(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.LATEST_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        # Nothing was left for a Back Door sync to import as its own code.
        self._sync(gateway, self.BACK)
        self.assertFalse(DoorCode.objects.filter(label="Slot 2").exists())


class ScheduleTests(_ReconcileTestBase):
    def test_a_schedule_change_goes_on_to_the_added_lock(self):
        master, gateway = self._master_on_both()

        result = self._sync_front(gateway, days=self.WEEKDAYS)

        self.assertIn("sent_to_other_locks", self._slot_row(result, 1).warnings)
        master.refresh_from_db()
        self.assertEqual((master.days_of_week, master.window_start.isoformat()), (self.WEEKDAYS, "08:00:00"))
        self.assertIsNotNone(self._back(master).reconcile_requested_at)

        self._push_requested(gateway)

        # Only the schedule goes, into the slot that has the PIN.
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(sorted(self._schedule_calls(gateway)), [(12, 2, day, 8) for day in (1, 2, 3, 4, 5)])
        back = self._back(master)
        self.assertEqual((back.slot_index, back.schedule_pending, back.push_state), (2, False, "pushed"))
        self.assertEqual(back.written_schedule, "31|08:00|18:00")
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

        # A later window on the same days goes the same way.
        gateway.invoke_calls.clear()
        self._sync_front(gateway, days=self.WEEKDAYS, start="09:00:00")
        self._push_requested(gateway)
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual({hour for _n, _u, _d, hour in self._schedule_calls(gateway)}, {9})

    def test_a_schedule_that_drops_days_is_cleared_and_pushed_again(self):
        # Sending the new days only would leave the dropped days' windows on the lock.
        master, gateway = self._master_on_both()
        self._sync_front(gateway, days=self.WEEKDAYS)
        self._push_requested(gateway)

        for days, expected_weekdays in ((self.MON_WED, [1, 3]), (None, [])):
            with self.subTest(days=days):
                gateway.invoke_calls.clear()
                self._sync_front(gateway, days=days)
                self._push_requested(gateway)

                self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
                self.assertEqual(self._calls(gateway, "set"), [(12, [2, 1, self.PIN])])
                self.assertEqual(sorted(w for _n, _u, w, _h in self._schedule_calls(gateway)), expected_weekdays)
                self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
                self.assertEqual(DoorCode.objects.get(id=master.id).push_state, DoorCode.PushState.PUSHED)

    def test_a_dropped_day_landing_while_the_last_schedule_goes_out_isnt_lost(self):
        # Review 2, item 2: the schedule push in flight records what it wrote, and the reconcile goes again.
        master, gateway = self._master_on_both()
        self._sync_front(gateway, days=self.WEEKDAYS)
        self._before_call(
            gateway,
            node_id=12,
            command_class=78,
            method_name="setDailyRepeatingSchedule",
            hook=lambda: self._sync_front(gateway, days=self.MON_WED),
        )

        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        # The last schedule sent is the new one, into the slot pushed again after the clear.
        after_clear = gateway.invoke_calls[[c["method_name"] for c in gateway.invoke_calls].index("clear") :]
        weekdays = sorted(
            c["args"][1]["weekdays"][0] for c in after_clear if c["method_name"] == "setDailyRepeatingSchedule"
        )
        self.assertEqual(weekdays, [1, 3])
        back = self._back(master)
        self.assertEqual((back.written_schedule, back.reconcile_requested_at), ("5|08:00|18:00", None))
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

    def test_a_schedule_from_the_value_cache_only_goes_out_once_the_lock_confirms_it(self):
        master, gateway = self._master_on_both()
        live: list = [None]
        self._front_schedule_from_cache(gateway, live)

        # The cache says Mon-Fri, the lock has no schedule.
        row = self._slot_row(self._sync_front(gateway, days=self.WEEKDAYS), 1)
        self.assertIn("schedule_change_unconfirmed", row.warnings)
        self.assertNotIn("sent_to_other_locks", row.warnings)
        self.assertIsNone(DoorCode.objects.get(id=master.id).days_of_week)
        self.assertIsNone(self._back(master).reconcile_requested_at)

        live[0] = (self.WEEKDAYS, (8, 0), (18, 0))
        row = self._slot_row(self._sync_front(gateway, days=self.WEEKDAYS), 1)
        self.assertIn("sent_to_other_locks", row.warnings)
        self.assertEqual(DoorCode.objects.get(id=master.id).days_of_week, self.WEEKDAYS)
        self._push_requested(gateway)

        # A schedule the cache alone says is gone is never sent on either.
        row = self._slot_row(self._sync_front(gateway, days=None), 1)
        self.assertIn("schedule_change_unconfirmed", row.warnings)
        self.assertEqual(DoorCode.objects.get(id=master.id).days_of_week, self.WEEKDAYS)
        self.assertIsNone(self._back(master).reconcile_requested_at)

        live[0] = None
        self._sync_front(gateway, days=None)
        self.assertIsNone(DoorCode.objects.get(id=master.id).days_of_week)
        self.assertIsNotNone(self._back(master).reconcile_requested_at)


class OffCodeTests(_ReconcileTestBase):
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
        self._push_requested(gateway)
        self._push_pending(gateway)
        self.assertEqual(self._node_calls(gateway), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertIsNotNone(self._back(master).reconcile_requested_at)

        disabled.clear()
        self._sync_front(gateway)
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self._push_requested(gateway)
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_an_off_code_keeps_its_window_on_the_added_lock_until_its_back_on(self):
        master, gateway = self._master_on_both()
        self._sync_front(gateway, days=self.WEEKDAYS)
        self._push_requested(gateway)
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)

        self._sync_front(gateway, days=self.MON_WED)

        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)
        gateway.invoke_calls.clear()
        self._push_requested(gateway)
        self._push_pending(gateway)
        self.assertEqual(self._node_calls(gateway), [])

        disabled.clear()
        self._sync_front(gateway, days=self.MON_WED)
        self._push_requested(gateway)
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(sorted(w for _n, _u, w, _h in self._schedule_calls(gateway)), [1, 3])


class HeldPinTests(_ReconcileTestBase):
    def test_another_code_with_the_new_pin_takes_the_code_off_that_lock_until_a_later_change(self):
        # The Back Door's slot 1 code has that PIN, so a push would put it in a second slot (#188).
        # The old PIN was changed on purpose, so it still comes off.
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, OTHER_PIN)

        row = self._slot_row(self._sync_front(gateway), 1)
        self.assertIn("pin_held_on_other_lock", row.warnings)
        self.assertNotIn("sent_to_other_locks", row.warnings)

        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.push_state), (None, DoorCode.PushState.FAILED))
        # The id isn't checked: stored errors mask any run of 4-8 digits, and test ids run that high on Postgres.
        self.assertIn(f"{self.BACK} already has this PIN in slot 1 as door code ", back.last_push_error)
        self.assertIn('("Slot 1"), so this code is off that lock', back.last_push_error)
        self._push_pending(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

        # Review 3, item 4: a later PIN that doesn't clash brings the lock back.
        self._change_front_pin(gateway, self.LATEST_PIN)
        self._sync_front(gateway)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.LATEST_PIN})
        self.assertEqual(self._back(master).push_state, DoorCode.PushState.PUSHED)

    def test_retry_puts_the_code_back_once_the_other_code_is_deleted(self):
        master, gateway = self._master_on_both()
        other = DoorCode.objects.get(lock_assignments__lock_entity_id=self.BACK, lock_assignments__slot_index=1)
        self._change_front_pin(gateway, OTHER_PIN)
        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._delete(other, gateway).status_code, 204)
        door_codes_uc.retry_push_door_code(
            code=DoorCode.objects.get(id=master.id), actor_user=self.user, zwavejs=gateway
        )

        self.assertEqual(list(self._lock_codes(gateway, 12).values()), [OTHER_PIN])
        self.assertIsNotNone(self._back(master).slot_index)


class CapTests(_ReconcileTestBase):
    def test_a_reconcile_stuck_on_the_added_lock_doesnt_freeze_the_front_door(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        gateway.clear_fails_on.add(12)
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            push_attempt_count=lock_push_uc._push_max_attempts() - 1
        )

        self._push_requested(gateway)

        # At the cap the lock is failed, and nothing is on record as a clear failure.
        back = self._back(master)
        self.assertEqual(back.push_state, DoorCode.PushState.FAILED)
        self.assertIn("Couldn't clear slot 2", back.last_push_error)
        self.assertFalse(self._clear_failed_events(master).exists())

        # The Front Door still decides the PIN, and that re-arms the Back Door...
        self._change_front_pin(gateway, self.LATEST_PIN)
        row = self._slot_row(self._sync_front(gateway), 1)
        self.assertNotEqual(row.action, "skipped")
        self.assertEqual(self._pin(master), self.LATEST_PIN)
        back = self._back(master)
        self.assertEqual((back.push_state, back.push_attempt_count), (DoorCode.PushState.PENDING, 0))

        # ...and a PIN deleted there still turns the code off.
        del gateway._lock_codes[(14, 1)]
        del gateway._cache_codes[(14, 1)]
        self._sync_front(gateway)
        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)

    def test_retry_runs_a_capped_reconcile_again(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        gateway.clear_fails_on.add(12)
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            push_attempt_count=lock_push_uc._push_max_attempts() - 1
        )
        self._push_requested(gateway)
        self.assertEqual(self._back(master).push_state, DoorCode.PushState.FAILED)

        gateway.clear_fails_on.clear()
        door_codes_uc.retry_push_door_code(
            code=DoorCode.objects.get(id=master.id), actor_user=self.user, zwavejs=gateway
        )

        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(self._back(master).push_state, DoorCode.PushState.PUSHED)


# The tests above again with the FakeGateway default, where a set doesn't reach
# the value cache, so every sync after a push sees the pushed slot as Available.
class StaleCachePinChangeTests(PinChangeTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheRaceTests(RaceTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheScheduleTests(ScheduleTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheOffCodeTests(OffCodeTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheHeldPinTests(HeldPinTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheCapTests(CapTests):
    CACHE_UPDATES_ON_SET = False


class Migration0012Tests(TransactionTestCase):
    """Migration 0012 is additive: old rows read as nothing written known and nothing to reconcile."""

    BEFORE = [("locks", "0011_assignment_push_requested")]
    AFTER = [("locks", "0012_assignment_written_and_reconcile")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_forward_keeps_rows_with_nothing_known_and_back_again(self):
        old = self._migrate(self.BEFORE)
        user = old.get_model("accounts", "User").objects.create(email="u@example.com", password="x")
        code = old.get_model("locks", "DoorCode").objects.create(user_id=user.id, code_type="permanent")
        assignment = old.get_model("locks", "DoorCodeLockAssignment").objects.create(
            door_code_id=code.id, lock_entity_id="lock.back_door", slot_index=2
        )

        new = self._migrate(self.AFTER)
        row = new.get_model("locks", "DoorCodeLockAssignment").objects.get(id=assignment.id)
        self.assertEqual(
            (row.slot_index, row.written_pin, row.written_schedule, row.reconcile_requested_at), (2, None, None, None)
        )

        self._migrate(self.BEFORE)
        row = old.get_model("locks", "DoorCodeLockAssignment").objects.get(id=assignment.id)
        self.assertEqual(row.slot_index, 2)
        self._migrate(self.AFTER)
