"""A new PIN or schedule lock sync takes from the Front Door goes on to the added Back Door (issue #220).

The master code was imported from the Front Door (node 14, slot 1) and the
Back Door (node 12) was added to it, where latchpoint pushed it into slot 2.
Lock sync of the Front Door only flags the Back Door; the queued push task's
reconcile (``locks.use_cases.added_lock_reconcile``) brings it in line,
reading the slot live and comparing it with what latchpoint last wrote there.
"""

from __future__ import annotations

from datetime import time, timedelta
from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
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
    OLDER_PIN = "2468"
    MONDAY = 0b0000001
    WEEKDAYS = 0b0011111  # Mon-Fri
    MON_WED = 0b0000101

    def _pin(self, code: DoorCode) -> str | None:
        code.refresh_from_db()
        return SettingsEncryption.get().decrypt(code.encrypted_pin) if code.encrypted_pin else None

    def _back(self, master: DoorCode) -> DoorCodeLockAssignment:
        return DoorCodeLockAssignment.objects.get(door_code=master, lock_entity_id=self.BACK)

    def _pushed_before_0012(self, master: DoorCode) -> None:
        """The Back Door was added and pushed by #219, before migration 0012 recorded what a push wrote."""
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            written_pin=None, written_schedule=None
        )

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

    def test_a_slot_pushed_before_0012_has_the_old_pin_cleared_when_the_pin_changes(self):
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._calls(gateway, "set"), [(12, [2, 1, self.NEW_PIN])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        self.assertEqual(self._slots(master), {self.FRONT: 1, self.BACK: 2})
        # Recorded from now on.
        back = self._back(master)
        self.assertEqual(SettingsEncryption.get().decrypt(back.written_pin), self.NEW_PIN)
        self.assertEqual(back.written_schedule, "")

    def test_a_masked_slot_pushed_before_0012_has_the_old_pin_cleared_too(self):
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        self._mask_reads(gateway, node=12)
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_a_slot_pushed_before_0012_that_fell_behind_is_cleared_not_let_go(self):
        # Review of the redesign, item 1: the slot still has A while the code
        # already took B, then C arrives. Nothing was recorded, so A is taken as
        # latchpoint's older PIN, the way every clear treated the slot before.
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        gateway._lock_codes[(12, 2)] = gateway._cache_codes[(12, 2)] = self.OLDER_PIN
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})
        # Nothing left for a Back Door sync to import as its own code.
        self._sync(gateway, self.BACK)
        self.assertFalse(DoorCode.objects.filter(label="Slot 2").exists())

    def test_a_delete_clears_a_slot_pushed_before_0012_that_fell_behind(self):
        # The same as main does: a slot latchpoint pushed with nothing recorded is cleared.
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        gateway._lock_codes[(12, 2)] = gateway._cache_codes[(12, 2)] = self.OLDER_PIN

        response = self._delete(master, gateway)

        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})

    def test_a_config_slot_is_never_taken_for_latchpoints_pin(self):
        # Messaging or passage mode is lock config, so it's let go untouched even with nothing recorded.
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        handle = gateway._handle_user_code_call

        def handle_user_code_call(*, node_id: int, method_name: str, args: list):
            if method_name == "get" and (node_id, int(args[0])) == (12, 2):
                return {"userIdStatus": 3, "userCode": ""}
            return handle(node_id=node_id, method_name=method_name, args=args)

        gateway._handle_user_code_call = handle_user_code_call
        self._change_front_pin(gateway, self.NEW_PIN)

        self._sync_front(gateway)
        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertNotEqual(self._back(master).slot_index, 2)

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


class PartialScheduleTests(_ReconcileTestBase):
    """Review of the redesign, item 2: a schedule push that stops partway leaves days nothing recorded."""

    @staticmethod
    def _fail_nth_schedule_write(gateway, nth: int) -> None:
        """The Back Door stops answering on the ``nth`` CC 78 schedule write, once."""
        invoke = gateway.invoke_cc_api
        seen = [0]

        def invoke_cc_api(**kwargs):
            if (kwargs["node_id"], kwargs["command_class"], kwargs["method_name"]) == (
                12,
                78,
                "setDailyRepeatingSchedule",
            ):
                seen[0] += 1
                if seen[0] == nth:
                    raise TIMEOUT
            return invoke(**kwargs)

        gateway.invoke_cc_api = invoke_cc_api

    def _monday_to_friday_cut_short(self):
        """Mon-Fri goes to the Back Door, which stops answering after Monday and Tuesday."""
        master, gateway = self._master_on_both()
        self._fail_nth_schedule_write(gateway, 3)
        self._sync_front(gateway, days=self.WEEKDAYS)
        self._push_requested(gateway)
        self.assertEqual(sorted(w for _n, _u, w, _h in self._schedule_calls(gateway)), [1, 2])
        # Not known what's in the slot now.
        self.assertIsNone(self._back(master).written_schedule)
        gateway.invoke_calls.clear()
        return master, gateway

    def test_case_a_a_partial_mon_to_fri_then_monday_only_clears_the_slot(self):
        master, gateway = self._monday_to_friday_cut_short()

        self._sync_front(gateway, days=self.MONDAY)
        self._push_requested(gateway)

        # Sending Monday alone would leave Tuesday's window on the lock.
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(sorted(w for _n, _u, w, _h in self._schedule_calls(gateway)), [1])
        back = self._back(master)
        self.assertEqual((back.written_schedule, back.reconcile_requested_at), ("1|08:00|18:00", None))
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

    def test_case_b_a_partial_mon_to_fri_then_no_schedule_clears_the_slot(self):
        master, gateway = self._monday_to_friday_cut_short()

        self._sync_front(gateway, days=None)
        self._push_requested(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._schedule_calls(gateway), [])
        self.assertEqual(self._back(master).written_schedule, "")
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})


class OffCodeTests(_ReconcileTestBase):
    def test_turning_the_code_back_on_long_after_the_change_flags_the_back_door_again(self):
        # Review of the redesign, item 3: the flag from before the code went off is past the queued
        # task's 10 minutes, so turning it back on flags it again rather than wait for the 300s retry.
        master, gateway = self._master_on_both()
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        long_ago = timezone.now() - lock_push_uc.PUSH_REQUEST_TTL - timedelta(minutes=1)
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            reconcile_requested_at=long_ago
        )

        disabled.clear()
        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertIn("sent_to_other_locks", row.warnings)
        self.assertGreater(self._back(master).reconcile_requested_at, long_ago)
        self.assertEqual(self.woken, ["push_requested_door_codes"])
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_turning_the_code_back_on_before_its_taken_off_leaves_the_lock_in_line(self):
        # Off at the Front Door flags the Back Door to take it off (issue #221), but
        # it's back on before that ran: the reconcile finds the PIN there and keeps it.
        master, gateway = self._master_on_both()
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)
        self._sync_front(gateway)
        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)

        disabled.clear()
        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertIn("sent_to_other_locks", row.warnings)
        gateway.invoke_calls.clear()
        self._push_requested(gateway)
        self.assertEqual(self._node_calls(gateway), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertIsNone(self._back(master).reconcile_requested_at)

    def test_an_off_code_with_a_new_pin_comes_off_the_added_lock_and_goes_back_with_the_new_pin(self):
        # Issue #221: a code the Front Door turns off (confirmed live) comes off the
        # added locks, rather than keep its old PIN there until it's back on.
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
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        self.assertIsNone(self._back(master).reconcile_requested_at)

        disabled.clear()
        gateway.invoke_calls.clear()
        self._sync_front(gateway)
        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self._push_requested(gateway)
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_an_off_code_with_a_new_window_comes_off_the_added_lock_and_goes_back_with_it(self):
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
        self.assertEqual(
            self._node_calls(gateway), [{"node_id": 12, "command_class": 99, "method_name": "clear", "args": [2]}]
        )

        disabled.clear()
        gateway.invoke_calls.clear()
        self._sync_front(gateway, days=self.MON_WED)
        self._push_requested(gateway)
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
        self.assertEqual(sorted(w for _n, _u, w, _h in self._schedule_calls(gateway)), [1, 3])
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


class GuardTests(_ReconcileTestBase):
    """The checks a run makes that the scheduler's query already made once (review of the redesign, item 5)."""

    def _flagged(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        self.assertIsNotNone(self._back(master).reconcile_requested_at)
        return master, gateway

    def _reconcile(self, master: DoorCode, gateway) -> str:
        return reconcile_uc.reconcile_added_lock(door_code_id=master.id, lock_entity_id=self.BACK, zwavejs=gateway)

    def test_a_code_turned_off_after_it_was_picked_waits(self):
        # M18: off between the due query and the lock_sync lock.
        for fields in ({"is_active": False}, {"start_at": timezone.now() + timedelta(days=1)}):
            with self.subTest(fields=list(fields)):
                master, gateway = self._flagged()
                DoorCode.objects.filter(id=master.id).update(**fields)

                self.assertEqual(self._reconcile(master, gateway), reconcile_uc.WAITING)

                self.assertEqual(self._node_calls(gateway), [])
                self.assertIsNotNone(self._back(master).reconcile_requested_at)
                self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})
                DoorCode.objects.all().delete()

    def test_a_run_out_of_its_time_budget_isnt_counted(self):
        master, gateway = self._flagged()

        outcome = self._reconcile(master, lock_push_uc.BudgetedGateway(gateway, seconds=0))

        self.assertEqual(outcome, reconcile_uc.RETRY)
        back = self._back(master)
        self.assertEqual((back.push_attempt_count, back.push_state), (0, DoorCode.PushState.PENDING))
        self.assertIsNotNone(back.reconcile_requested_at)

        # One that got no answer in time is.
        gateway._get_scripts[12] = [TIMEOUT] * 3
        self.assertEqual(self._reconcile(master, gateway), reconcile_uc.RETRY)
        self.assertEqual(self._back(master).push_attempt_count, 1)

    def test_the_180_attempt_check_leaves_a_flagged_lock_to_the_reconcile(self):
        # M14.
        master, gateway = self._flagged()
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=master, lock_entity_id=self.BACK, slot_index=3, reason="driver TimeoutError", pin=self.PIN
        )

        self.assertEqual(lock_push_uc.synced_attempt_slots_to_check(door_code=master), [])

        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            reconcile_requested_at=None
        )
        self.assertEqual(lock_push_uc.synced_attempt_slots_to_check(door_code=master), [(self.BACK, 3)])

    def test_a_lock_being_removed_isnt_flagged(self):
        # M20: its clear owns it.
        master, gateway = self._master_on_both()
        lock_push_uc.record_clear_failure(
            door_code=master,
            lock_entity_id=self.BACK,
            slot_index=2,
            exc=TIMEOUT,
            expected_pin=self.PIN,
            removing=True,
        )

        flagged = reconcile_uc.flag_added_locks(
            door_code=DoorCode.objects.get(id=master.id), import_lock_entity_id=self.FRONT
        )

        self.assertEqual(flagged, [])
        self.assertIsNone(self._back(master).reconcile_requested_at)


class LateWriterTests(_ReconcileTestBase):
    """Review 4 of PR #223."""

    def _old_flag(self, master: DoorCode):
        """The Back Door's flag, from before the queued push task's 10 minutes."""
        long_ago = timezone.now() - lock_push_uc.PUSH_REQUEST_TTL - timedelta(minutes=1)
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            reconcile_requested_at=long_ago
        )
        return long_ago

    def test_a_push_that_picked_the_back_door_before_lock_sync_flagged_it_sends_nothing(self):
        # Item 1: the 300s push picks the Back Door, still owed its Mon-Fri schedule
        # after a push cut short, then the Front Door sync drops to Monday only and
        # flags it right before the push takes the lock.
        master, gateway = self._master_on_both()
        DoorCode.objects.filter(id=master.id).update(
            days_of_week=self.WEEKDAYS,
            window_start=time(8),
            window_end=time(18),
            code_type=DoorCode.CodeType.TEMPORARY,
        )
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            schedule_pending=True, push_state=DoorCode.PushState.PENDING, written_schedule=None
        )
        original = lock_push_uc._try_acquire_sync_lock
        fired: list[bool] = []

        def sync_front_first(*, lock_key: str):
            if lock_key == f"lock_sync:{self.BACK}" and not fired:
                fired.append(True)
                self._sync_front(gateway, days=self.MONDAY)
            return original(lock_key=lock_key)

        with patch.object(lock_push_uc, "_try_acquire_sync_lock", sync_front_first):
            self._push_pending(gateway)

        self.assertEqual(fired, [True])
        names = [c["method_name"] for c in gateway.invoke_calls if c["node_id"] == 12]
        # Nothing went out before the reconcile's clear, and then only Monday.
        self.assertIn("clear", names)
        self.assertNotIn("setDailyRepeatingSchedule", names[: names.index("clear")])
        self.assertEqual(sorted(w for _n, _u, w, _h in self._schedule_calls(gateway)), [1])
        back = self._back(master)
        self.assertEqual((back.written_schedule, back.reconcile_requested_at), ("1|08:00|18:00", None))

    def test_turning_a_code_off_and_on_takes_a_slot_with_nothing_recorded_off_and_puts_it_back(self):
        # Item 2, after issue #221: going off (confirmed live) takes the code's PIN off
        # the slot, and with nothing recorded the scheduler's push puts it back once
        # it's on again, rather than a flag.
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)
        self._sync_front(gateway)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN})
        disabled.clear()

        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertNotIn("sent_to_other_locks", row.warnings)
        self.assertIsNone(self._back(master).reconcile_requested_at)
        self._push_pending(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.PIN})

    def _unclear_second_read(self, gateway) -> None:
        """Back Door slot 2 reads back with another PIN, then with no clear status."""
        gateway._lock_codes[(12, 2)] = gateway._cache_codes[(12, 2)] = self.OLDER_PIN
        gateway._get_scripts[12] = [{"userIdStatus": 1, "userCode": self.OLDER_PIN}, {"userIdStatus": 254}]

    def test_an_unclear_second_read_clears_nothing_on_reconcile(self):
        # Item 3.
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        self._unclear_second_read(gateway)

        self._push_requested(gateway)

        self.assertEqual(self._node_calls(gateway), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.OLDER_PIN})
        back = self._back(master)
        self.assertEqual((back.slot_index, back.push_attempt_count), (2, 1))
        self.assertIsNotNone(back.reconcile_requested_at)

    def test_an_unclear_second_read_clears_nothing_on_delete(self):
        master, gateway = self._master_on_both()
        self._pushed_before_0012(master)
        self._unclear_second_read(gateway)

        response = self._delete(master, gateway)

        self.assertNotEqual(response.status_code, 204, response.content)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.OLDER_PIN})
        self.assertTrue(DoorCode.objects.filter(id=master.id).exists())

    def test_turning_a_code_back_on_says_when_another_code_has_its_pin_on_an_added_lock(self):
        master, gateway = self._master_on_both()
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)
        self._change_front_pin(gateway, OTHER_PIN)
        self._sync_front(gateway)
        disabled.clear()

        row = self._slot_row(self._sync_front(gateway), 1)

        self.assertIn("pin_held_on_other_lock", row.warnings)
        self.assertNotIn("sent_to_other_locks", row.warnings)

    def test_a_schedule_recorded_differently_is_flagged_when_the_code_comes_back_on(self):
        # Mutants 6 and 10. Going off (confirmed live) flags it too since issue #221,
        # but to take the PIN off, not to send the schedule.
        master, gateway = self._master_on_both()
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            written_schedule="31|08:00|18:00"
        )
        disabled: set[tuple[int, int]] = {(14, 1)}
        self._disable_slots(gateway, disabled)

        self._sync_front(gateway)

        self.assertFalse(DoorCode.objects.get(id=master.id).is_active)
        self.assertEqual(self._back(master).last_push_error, reconcile_uc.OFF_WAITING_ERROR)

        disabled.clear()
        self._sync_front(gateway)
        back = self._back(master)
        self.assertIsNotNone(back.reconcile_requested_at)
        self.assertEqual(back.last_push_error, reconcile_uc.WAITING_ERROR)

    def test_turning_an_off_code_on_flags_a_lock_only_when_its_behind(self):
        # The same rule on a code turned off before issue #221, so nothing flagged it then.
        master, gateway = self._master_on_both()
        DoorCode.objects.filter(id=master.id).update(is_active=False)

        self._sync_front(gateway)

        self.assertTrue(DoorCode.objects.get(id=master.id).is_active)
        self.assertIsNone(self._back(master).reconcile_requested_at)

        DoorCode.objects.filter(id=master.id).update(is_active=False)
        DoorCodeLockAssignment.objects.filter(door_code=master, lock_entity_id=self.BACK).update(
            written_schedule="31|08:00|18:00"
        )
        self._sync_front(gateway)
        self.assertIsNotNone(self._back(master).reconcile_requested_at)

    def test_turning_a_code_on_from_latchpoint_takes_up_an_old_flag(self):
        # #189: request_push, which turning a code on queues, flags its waiting added locks again from now.
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        long_ago = self._old_flag(master)

        lock_push_uc.request_push(DoorCode.objects.get(id=master.id))

        self.assertGreater(self._back(master).reconcile_requested_at, long_ago)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})

    def test_a_code_reaching_its_start_takes_up_an_old_flag(self):
        master, gateway = self._master_on_both()
        self._change_front_pin(gateway, self.NEW_PIN)
        self._sync_front(gateway)
        long_ago = self._old_flag(master)
        DoorCode.objects.filter(id=master.id).update(
            start_at=timezone.now() - timedelta(minutes=1), last_push_attempt_at=timezone.now() - timedelta(hours=1)
        )

        self._enforce(gateway)

        self.assertGreater(self._back(master).reconcile_requested_at, long_ago)
        self._push_requested(gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {1: OTHER_PIN, 2: self.NEW_PIN})


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


class StaleCachePartialScheduleTests(PartialScheduleTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheGuardTests(GuardTests):
    CACHE_UPDATES_ON_SET = False


class StaleCacheLateWriterTests(LateWriterTests):
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
