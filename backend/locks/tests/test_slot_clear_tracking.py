"""Issues #158, #161 and #151: what's left to clear on a lock, and how it's tracked and exposed."""

from __future__ import annotations

import contextlib
import importlib
import json
from unittest.mock import patch

from django.apps import apps as django_apps
from django.urls import reverse
from integrations_zwavejs.manager import ZwavejsCommandError
from rest_framework.test import APIClient, APITestCase

from alarm.crypto import SettingsEncryption
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.serializers import DoorCodePushSerializer, DoorCodeSerializer
from locks.tests.test_lock_push import ClearFailingGateway, FakeGateway, _TwoLockUpdateTestBase
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_push as lock_push_uc


def _timeouts(count: int = 3) -> list[Exception]:
    return [ZwavejsCommandError("driver TimeoutError after 5.0s") for _ in range(count)]


class _SlotClearTestBase(_TwoLockUpdateTestBase):
    def _run_scheduler(self, gateway: FakeGateway) -> int:
        from locks.tasks import push_pending_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            return push_pending_door_codes()

    def _turned_off_without_clearing(self, lock_entity_ids: list[str]) -> tuple[DoorCode, ClearFailingGateway]:
        """A code left inactive and ``pushed`` with its slots still tracked and no clear failure (#138 rows)."""
        code, gateway = self._pushed_code(lock_entity_ids)
        DoorCode.objects.filter(id=code.id).update(is_active=False)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
        return code, gateway

    def _code_with_side_unconfirmed(self) -> tuple[DoorCode, ClearFailingGateway]:
        """A code on Back and Side whose PIN landed on Side but every readback there timed out."""
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True, get_responses={13: _timeouts()})
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            lock_entity_ids=[self.BACK, self.SIDE],
            actor_user=self.user,
            zwavejs=gateway,
        )
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: None})
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [self.SIDE])
        gateway.invoke_calls.clear()
        return code, gateway

    @staticmethod
    def _serialize(code: DoorCode, serializer=DoorCodeSerializer) -> dict:
        return serializer(DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)).data


class InactiveCodeSlotClearTests(_SlotClearTestBase):
    """Issue #158: the scheduler and Retry clear an inactive code's slots that have no clear failure on record."""

    def test_scheduler_clears_an_inactive_code_still_holding_a_slot(self):
        code, gateway = self._turned_off_without_clearing([self.BACK, self.SIDE])

        self.assertEqual(self._run_scheduler(gateway), 1)

        code.refresh_from_db()
        self.assertCountEqual(self._calls(gateway, "clear"), [(12, [1]), (13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: None})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")

        # Nothing left, so the next tick leaves it alone.
        gateway.invoke_calls.clear()
        self.assertEqual(self._run_scheduler(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

    def test_retry_clears_an_inactive_code_still_holding_a_slot(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])

        result = door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [1])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(result), {self.BACK: None})
        self.assertEqual(result.push_state, DoorCode.PushState.PUSHED)
        self.assertFalse(result.is_active)

    def test_retry_through_the_api_clears_instead_of_returning_409(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])
        client = APIClient()
        client.force_authenticate(self.user)

        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = client.post(reverse("door-code-push", args=[code.id]))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["pending_slot_clears"], [])
        self.assertEqual(self._lock_codes(gateway, 12), {})

    def test_a_clear_that_fails_is_recorded_and_retried_until_it_works(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])
        gateway.clear_fails_on = {12}

        self._run_scheduler(gateway)

        code.refresh_from_db()
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", code.last_push_error)
        [failure] = lock_push_uc.unresolved_clear_failures(door_code=code)
        self.assertEqual((failure.lock_entity_id, failure.slot_index, failure.removing), (self.BACK, 1, False))
        self.assertEqual(failure.expected_pin, self.PIN)

        gateway.clear_fails_on = set()
        self._run_scheduler(gateway)

        code.refresh_from_db()
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(self._calls(gateway, "set"), [])

    def test_a_clear_that_keeps_failing_hits_the_attempt_cap(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])
        gateway.clear_fails_on = {12}

        with patch("locks.tasks._get_push_max_attempts", return_value=2):
            self._run_scheduler(gateway)
            self._run_scheduler(gateway)
            self.assertEqual(self._run_scheduler(gateway), 0)

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertTrue(code.last_push_error.startswith(f"Couldn't clear slot 1 on {self.BACK}"))

    def test_scheduler_checks_an_unconfirmed_slot_of_an_inactive_code_and_clears_it(self):
        code, gateway = self._code_with_side_unconfirmed()
        # Turned off by a save that didn't run the cleanup, so nothing records a failure.
        door_codes_uc.update_door_code(code=code, changes={"is_active": False}, actor_user=self.user)
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=self.BACK).update(slot_index=None)
        gateway._lock_codes.pop((12, 1))

        self.assertEqual(self._run_scheduler(gateway), 1)

        code.refresh_from_db()
        self.assertEqual(self._calls(gateway, "clear"), [(13, [1])])
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [])
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_an_unconfirmed_slot_holding_another_pin_is_settled_without_a_clear(self):
        code, gateway = self._code_with_side_unconfirmed()
        door_codes_uc.update_door_code(code=code, changes={"is_active": False}, actor_user=self.user)
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=self.BACK).update(slot_index=None)
        gateway._lock_codes[(13, 1)] = "9999"  # someone typed another code into that slot since

        self._run_scheduler(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 13), {1: "9999"})
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [])
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, DoorCode.PushState.PUSHED)

    def test_an_unconfirmed_slot_another_code_now_holds_is_never_touched(self):
        code, gateway = self._code_with_side_unconfirmed()
        door_codes_uc.update_door_code(code=code, changes={"is_active": False}, actor_user=self.user)
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=self.BACK).update(slot_index=None)
        other = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            push_state=DoorCode.PushState.PUSHED,
        )
        DoorCodeLockAssignment.objects.create(door_code=other, lock_entity_id=self.SIDE, slot_index=1)

        self.assertEqual(lock_push_uc.inactive_slots_to_clear(door_code=code), [])
        self._run_scheduler(gateway)
        with self.assertRaises(door_codes_uc.DoorCodeInactive):
            door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual([c for c in gateway.invoke_calls if c["node_id"] == 13], [])
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})

    def test_a_synced_inactive_code_is_left_alone(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])
        DoorCode.objects.filter(id=code.id).update(source=DoorCode.Source.SYNCED)
        code.refresh_from_db()

        self.assertEqual(self._run_scheduler(gateway), 0)
        with self.assertRaises(door_codes_uc.DoorCodeInactive):
            door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(self._serialize(code)["pending_slot_clears"], [])

    def test_a_code_turned_back_on_while_the_clear_waited_for_the_lock_is_left_alone(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])
        real_hold = lock_push_uc.hold_lock_sync

        @contextlib.contextmanager
        def hold_after_a_reactivate(lock_entity_ids, *, deadline=None):
            # An update that turned the code back on got the lock first.
            DoorCode.objects.filter(id=code.id).update(is_active=True)
            with real_hold(lock_entity_ids, deadline=deadline):
                yield

        with patch.object(lock_push_uc, "hold_lock_sync", hold_after_a_reactivate):
            still_failing = lock_push_uc.clear_inactive_code_slots(door_code=code, zwavejs=gateway)

        self.assertEqual(still_failing, [])
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})


class PendingInactiveCodesMigrationTests(_SlotClearTestBase):
    """Issue #158: the one-off data fix marks inactive manual codes that still hold a slot as pending."""

    @property
    def migration(self):
        return importlib.import_module("locks.migrations.0007_pending_inactive_door_codes_holding_slots")

    def test_marks_inactive_manual_codes_holding_a_slot_pending(self):
        stuck, _ = self._turned_off_without_clearing([self.BACK])
        cleared, _ = self._deactivated_code([self.SIDE])
        active, _ = self._pushed_code([self.FRONT])
        synced = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            encrypted_pin=SettingsEncryption.get().encrypt("1111"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=False,
            push_state=DoorCode.PushState.PUSHED,
        )
        DoorCodeLockAssignment.objects.create(door_code=synced, lock_entity_id=self.BACK, slot_index=4)
        failed = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("2222"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=False,
            push_state=DoorCode.PushState.FAILED,
        )
        DoorCodeLockAssignment.objects.create(door_code=failed, lock_entity_id=self.BACK, slot_index=5)

        self.migration._mark_pending(django_apps, None)

        states = dict(DoorCode.objects.values_list("id", "push_state"))
        self.assertEqual(
            states,
            {
                stuck.id: DoorCode.PushState.PENDING,
                cleared.id: DoorCode.PushState.PUSHED,
                active.id: DoorCode.PushState.PUSHED,
                synced.id: DoorCode.PushState.PUSHED,
                failed.id: DoorCode.PushState.FAILED,
            },
        )

    def test_reverse_is_a_no_op(self):
        [operation] = self.migration.Migration.operations
        self.assertIs(operation.reverse_code, operation.noop)


class UnconfirmedSlotSettledTests(_SlotClearTestBase):
    """Issue #161: once a cleanup checks or clears an unconfirmed slot, that lock stops being tied to the code."""

    def test_dropping_a_lock_settles_its_unconfirmed_slot(self):
        code, gateway = self._code_with_side_unconfirmed()

        self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        self.assertEqual(self._calls(gateway, "clear"), [(13, [1])])
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [])
        self.assertEqual(lock_push_uc.affected_lock_entity_ids(door_code=code), {self.BACK})
        marker = DoorCodeEvent.objects.get(door_code=code, metadata__action="unconfirmed_resolved")
        self.assertEqual(
            (marker.lock_entity_id, marker.metadata["slot_index"], marker.metadata["outcome"]),
            (self.SIDE, 1, "cleared"),
        )

    def test_delete_isnt_refused_by_a_dropped_lock_whose_slot_was_already_cleared(self):
        code, gateway = self._code_with_side_unconfirmed()
        self._update(code, gateway, {"lock_entity_ids": [self.BACK]})
        # Side goes offline afterwards.
        gateway._get_scripts = {13: _timeouts()}
        gateway.clear_fails_on = {13}
        gateway.invoke_calls.clear()

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual([c for c in gateway.invoke_calls if c["node_id"] == 13], [])
        self.assertEqual(self._lock_codes(gateway, 12), {})

    def test_later_updates_dont_check_the_dropped_lock_again(self):
        code, gateway = self._code_with_side_unconfirmed()
        self._update(code, gateway, {"lock_entity_ids": [self.BACK]})
        gateway.invoke_calls.clear()

        self._update(code, gateway, {"code": "5555"})

        self.assertEqual([c for c in gateway.invoke_calls if c["node_id"] == 13], [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: "5555"})

    def test_a_slot_whose_check_timed_out_stays_tied_until_a_retry_clears_it(self):
        code, gateway = self._code_with_side_unconfirmed()
        gateway._get_scripts = {13: _timeouts()}

        self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [self.SIDE])
        self.assertIn(self.SIDE, lock_push_uc.affected_lock_entity_ids(door_code=code))

        self._run_scheduler(gateway)

        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [])
        self.assertEqual(lock_push_uc.affected_lock_entity_ids(door_code=code), {self.BACK})

    def test_a_new_attempt_on_a_settled_slot_counts_again(self):
        code, gateway = self._code_with_side_unconfirmed()
        self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id=self.SIDE, slot_index=1, reason="timeout", pin=self.PIN
        )

        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [self.SIDE])
        self.assertEqual(lock_push_uc._unconfirmed_attempt_slots(door_code=code, lock_entity_id=self.SIDE), [1])


class PendingSlotClearsSerializerTests(_SlotClearTestBase, APITestCase):
    """Issue #151: the API says which slot clears are outstanding and which locks are being removed."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def _failed_drop_of_side(self) -> tuple[DoorCode, ClearFailingGateway]:
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {13}
        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK]})
        gateway.invoke_calls.clear()
        return code, gateway

    def _patch(self, code: DoorCode, gateway: FakeGateway, body: dict) -> dict:
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.patch(
                reverse("door-code-detail", args=[code.id]), {**body, "reauth_password": "pass"}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]

    def test_a_failed_drop_shows_its_pending_clear_and_pending_removal(self):
        code, _gateway = self._failed_drop_of_side()

        data = self.client.get(reverse("door-code-detail", args=[code.id])).json()["data"]

        self.assertEqual(
            data["pending_slot_clears"], [{"lock_entity_id": self.SIDE, "slot_index": 1, "removing": True}]
        )
        self.assertEqual(data["lock_entity_ids"], [self.BACK, self.SIDE])
        self.assertCountEqual(
            data["lock_slot_assignments"],
            [
                {"lock_entity_id": self.BACK, "slot_index": 1, "pending_removal": False},
                {"lock_entity_id": self.SIDE, "slot_index": 1, "pending_removal": True},
            ],
        )

    def test_a_kept_lock_with_a_failed_clear_is_not_pending_removal(self):
        code, gateway = self._pushed_code([self.BACK])
        gateway.clear_fails_on = {12}
        code = self._update(code, gateway, {"code": "5555"})

        data = self._serialize(code)

        self.assertEqual(
            data["pending_slot_clears"], [{"lock_entity_id": self.BACK, "slot_index": 1, "removing": False}]
        )
        self.assertEqual(
            data["lock_slot_assignments"], [{"lock_entity_id": self.BACK, "slot_index": 1, "pending_removal": False}]
        )

    def test_an_inactive_code_holding_a_slot_lists_it_as_a_pending_clear(self):
        code, _gateway = self._turned_off_without_clearing([self.BACK])

        self.assertEqual(
            self._serialize(code)["pending_slot_clears"],
            [{"lock_entity_id": self.BACK, "slot_index": 1, "removing": False}],
        )

    def test_an_inactive_codes_unconfirmed_slot_is_listed_and_an_active_ones_isnt(self):
        code, _gateway = self._code_with_side_unconfirmed()
        # An active code's unconfirmed slot gets adopted by the next push, not cleared.
        self.assertEqual(self._serialize(code)["pending_slot_clears"], [])

        DoorCode.objects.filter(id=code.id).update(is_active=False)
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=self.BACK).update(slot_index=None)

        self.assertEqual(
            self._serialize(code)["pending_slot_clears"],
            [{"lock_entity_id": self.SIDE, "slot_index": 1, "removing": False}],
        )

    def test_a_settled_code_has_no_pending_clears(self):
        code, _gateway = self._deactivated_code([self.BACK])

        self.assertEqual(self._serialize(code)["pending_slot_clears"], [])

    def test_no_pin_is_exposed_by_the_new_fields(self):
        # The failed clear stores the old PIN (4321, encrypted) for the retry's readback.
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {12, 13}
        code = self._update(code, gateway, {"code": "5555", "lock_entity_ids": [self.BACK]})
        self.assertEqual(len(lock_push_uc.unresolved_clear_failures(door_code=code)), 2)

        data = self._serialize(code)
        push_data = self._serialize(code, DoorCodePushSerializer)

        for payload in (data["pending_slot_clears"], data["lock_slot_assignments"]):
            self.assertNotIn(self.PIN, json.dumps(payload))
            self.assertNotIn("5555", json.dumps(payload))
            self.assertNotIn("encrypted_pin", json.dumps(payload))
        self.assertEqual(
            {key for entry in data["pending_slot_clears"] for key in entry},
            {"lock_entity_id", "slot_index", "removing"},
        )
        # The old PIN only lives in the encrypted event metadata, and the push
        # response has no PIN at all. Ids and timestamps are left out of the
        # check since their digits can happen to match.
        noisy = {"id", "user_id", "created_at", "updated_at", "last_push_attempt_at", "last_used_at"}
        self.assertNotIn(self.PIN, json.dumps({k: v for k, v in data.items() if k not in noisy}))
        self.assertNotIn(self.PIN, json.dumps({k: v for k, v in push_data.items() if k not in noisy}))
        self.assertNotIn("5555", json.dumps({k: v for k, v in push_data.items() if k not in noisy}))
        self.assertEqual(data["pin"], "5555")

    def test_a_save_that_leaves_the_pending_removal_lock_out_keeps_removing_it(self):
        # What the edit form sends when the user adds Front without re-ticking Side.
        code, gateway = self._failed_drop_of_side()

        data = self._patch(code, gateway, {"lock_entity_ids": [self.BACK, self.FRONT]})

        self.assertEqual(
            data["pending_slot_clears"], [{"lock_entity_id": self.SIDE, "slot_index": 1, "removing": True}]
        )
        removal = {a["lock_entity_id"]: a["pending_removal"] for a in data["lock_slot_assignments"]}
        self.assertEqual(removal, {self.BACK: False, self.SIDE: True, self.FRONT: False})

        gateway.clear_fails_on = set()
        self._run_scheduler(gateway)
        self.assertEqual(self._slots(code), {self.BACK: 1, self.FRONT: 1})
        self.assertEqual(self._lock_codes(gateway, 13), {})

    def test_re_adding_the_pending_removal_lock_cancels_the_removal(self):
        code, gateway = self._failed_drop_of_side()

        data = self._patch(code, gateway, {"lock_entity_ids": [self.BACK, self.SIDE]})

        self.assertEqual(
            data["pending_slot_clears"], [{"lock_entity_id": self.SIDE, "slot_index": 1, "removing": False}]
        )
        self.assertFalse(any(a["pending_removal"] for a in data["lock_slot_assignments"]))
