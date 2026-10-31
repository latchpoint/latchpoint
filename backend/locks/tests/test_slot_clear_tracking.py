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
from alarm.models import Entity
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.serializers import DoorCodePushSerializer, DoorCodeSerializer
from locks.tests.test_door_code_locking import _recording_acquires
from locks.tests.test_lock_push import ClearFailingGateway, FakeGateway, _TwoLockUpdateTestBase
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.lock_config_sync import LockBusy
from locks.use_cases.lock_config_sync import NotFound as LockSyncNotFound


def _slot_fields(entry: dict) -> dict:
    """A ``lock_slot_assignments`` entry without the per-lock push fields (issue #126)."""
    return {key: entry[key] for key in ("lock_entity_id", "slot_index", "pending_removal")}


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

    def test_later_updates_and_deletes_dont_wait_on_the_dropped_lock(self):
        code, gateway = self._code_with_side_unconfirmed()
        self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        with _recording_acquires() as update_locks:
            self._update(code, gateway, {"code": "5555"})
        with _recording_acquires() as delete_locks:
            door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        # Before #161 both still took Side's lock_sync: lock, so a sync on Side held them up.
        self.assertNotIn(self.SIDE, update_locks)
        self.assertNotIn(self.SIDE, delete_locks)
        self.assertIn(self.BACK, update_locks)
        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())

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
        # The per-lock push fields (issue #126) are covered in test_assignment_push_state.
        self.assertCountEqual(
            [_slot_fields(entry) for entry in data["lock_slot_assignments"]],
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
            [_slot_fields(entry) for entry in data["lock_slot_assignments"]],
            [{"lock_entity_id": self.BACK, "slot_index": 1, "pending_removal": False}],
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

        # The per-lock push fields (issue #126) too, without the timestamp whose digits can happen to match.
        lock_slots = [
            {k: v for k, v in entry.items() if k not in ("last_push_attempt_at", "push_requested_at")}
            for entry in data["lock_slot_assignments"] + push_data["lock_slot_assignments"]
        ]
        for payload in (data["pending_slot_clears"], lock_slots):
            self.assertNotIn(self.PIN, json.dumps(payload))
            self.assertNotIn("5555", json.dumps(payload))
            self.assertNotIn("encrypted_pin", json.dumps(payload))
        self.assertEqual(
            {key for entry in data["pending_slot_clears"] for key in entry},
            {"lock_entity_id", "slot_index", "removing"},
        )
        self.assertEqual(
            {key for entry in data["lock_slot_assignments"] for key in entry},
            {
                "lock_entity_id",
                "slot_index",
                "pending_removal",
                "push_state",
                "last_push_error",
                "last_push_attempt_at",
                "push_attempt_count",
                "schedule_pending",
                "push_requested_at",
                "push_queued",
            },
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


class ClearResolvedDoesntHideALaterAttemptTests(_SlotClearTestBase):
    """PR #167 review: settling an old clear failure must not settle a newer unconfirmed attempt on that slot."""

    OLD_PIN = "1111"

    def _code(self) -> DoorCode:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            push_state=DoorCode.PushState.PENDING,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK, slot_index=None)
        return code

    def _attempt(self, code: DoorCode, pin: str, slot_index: int = 1) -> None:
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id=self.BACK, slot_index=slot_index, reason="timeout", pin=pin
        )

    def _failure(self, code: DoorCode, slot_index: int = 1) -> None:
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=self.BACK,
            slot_index=slot_index,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin=self.OLD_PIN,
            unconfirmed=True,
        )

    def _attempts(self, code: DoorCode) -> dict[int, str | None]:
        return lock_push_uc._unconfirmed_attempts(door_code=code, lock_entity_id=self.BACK)

    def test_the_retry_adopts_the_new_pins_slot_instead_of_stranding_it(self):
        for drops_duplicates in (False, True):
            with self.subTest(drops_duplicates=drops_duplicates):
                # A PIN change's cleanup couldn't check slot 1 for the old PIN, then
                # the new PIN landed in slot 1 but its readback timed out.
                gateway = ClearFailingGateway(
                    usersNumber=5, cache_updates_on_set=True, drops_duplicates=drops_duplicates
                )
                code = self._code()
                self._failure(code)
                self._attempt(code, self.PIN)
                gateway._lock_codes[(12, 1)] = self.PIN
                gateway._cache_codes[(12, 1)] = self.PIN

                self._run_scheduler(gateway)

                code.refresh_from_db()
                # Slot 1 doesn't hold the old PIN, which settles the old failure, but
                # the new PIN's attempt there was never checked, so it gets adopted.
                self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
                self.assertEqual(self._slots(code), {self.BACK: 1})
                self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
                self.assertEqual(self._calls(gateway, "set"), [])
                self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

                self._update(code, gateway, {"is_active": False})
                self.assertEqual(self._lock_codes(gateway, 12), {}, "the inactive code's PIN is still on the lock")
                DoorCode.objects.filter(id=code.id).delete()

    def test_a_not_holding_resolve_settles_the_attempts_before_its_failure(self):
        code = self._code()
        self._attempt(code, self.OLD_PIN)
        self._failure(code)

        lock_push_uc.resolve_clear_failure(
            door_code=code, lock_entity_id=self.BACK, slot_index=1, outcome="not_holding_pin"
        )

        self.assertEqual(self._attempts(code), {})
        # A later attempt on the slot counts again.
        self._attempt(code, self.PIN)
        self.assertEqual(self._attempts(code), {1: self.PIN})

    def test_a_clear_settles_every_attempt_before_it(self):
        code = self._code()
        self._failure(code)
        self._attempt(code, self.PIN)

        lock_push_uc.forget_cleared_slot(door_code=code, lock_entity_id=self.BACK, slot_index=1, outcome="cleared")

        # Whatever either PIN left in slot 1 went with the clear.
        self.assertEqual(self._attempts(code), {})


class ReactivatedWhileClearingTests(_SlotClearTestBase):
    """PR #167 review: the inactive clear must not write a stale state over an update that turned the code on."""

    def _reactivate_with_a_timed_out_push(self, code: DoorCode, gateway: FakeGateway) -> None:
        # What the update turning the code back on leaves when its push times out.
        DoorCode.objects.filter(id=code.id).update(
            is_active=True, push_state=DoorCode.PushState.PENDING, last_push_error="LockUnreachable: timed out"
        )
        DoorCodeLockAssignment.objects.filter(door_code=code).update(slot_index=None)
        gateway._lock_codes.pop((12, 1), None)
        gateway._cache_codes.pop((12, 1), None)

    def _assert_left_for_the_scheduler(self, code: DoorCode) -> None:
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(code.last_push_error, "LockUnreachable: timed out")

    def test_turned_on_while_the_clear_waited_for_the_lock(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])
        DoorCode.objects.filter(id=code.id).update(push_state=DoorCode.PushState.PENDING)
        real_hold = lock_push_uc.hold_lock_sync

        @contextlib.contextmanager
        def hold_after_a_reactivate(lock_entity_ids, *, deadline=None):
            self._reactivate_with_a_timed_out_push(code, gateway)
            with real_hold(lock_entity_ids, deadline=deadline):
                yield

        with patch.object(lock_push_uc, "hold_lock_sync", hold_after_a_reactivate):
            lock_push_uc.push_or_settle_after_clear_retry(door_code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self._assert_left_for_the_scheduler(code)

    def test_turned_on_right_after_the_clear(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])
        DoorCode.objects.filter(id=code.id).update(push_state=DoorCode.PushState.PENDING)
        # The rollup is the one write after the clear now (issue #126).
        real_refresh = lock_push_uc.refresh_push_state

        def refresh_after_a_reactivate(**kwargs):
            self._reactivate_with_a_timed_out_push(code, gateway)
            return real_refresh(**kwargs)

        with patch.object(lock_push_uc, "refresh_push_state", refresh_after_a_reactivate):
            lock_push_uc.push_or_settle_after_clear_retry(door_code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [1])])
        self._assert_left_for_the_scheduler(code)


class InactiveClearEdgeTests(_SlotClearTestBase):
    """PR #167 review: the inactive clear's readback, busy locks, and the slots it leaves to other paths."""

    def test_a_tracked_slot_is_read_back_before_its_cleared(self):
        cases = {
            # readback -> whether the slot gets cleared (it's forgotten either way)
            "this pin": ([], True),
            "this pin disabled": ([{"userIdStatus": 2, "userCode": self.PIN}], True),
            "masked": ([{"userIdStatus": 1, "userCode": "****"}], True),
            "disabled and unreadable": ([{"userIdStatus": 2, "userCode": "****"}], True),
            "a keypad code": ([{"userIdStatus": 1, "userCode": "9999"}], False),
            "empty": ([{"userIdStatus": 0, "userCode": ""}, {"userIdStatus": 0, "userCode": ""}], False),
        }
        for name, (readback, should_clear) in cases.items():
            with self.subTest(readback=name):
                code, gateway = self._turned_off_without_clearing([self.BACK])
                gateway._get_scripts = {12: list(readback)}

                self._run_scheduler(gateway)

                code.refresh_from_db()
                self.assertEqual(self._calls(gateway, "clear"), [(12, [1])] if should_clear else [])
                self.assertEqual(self._slots(code), {self.BACK: None})
                self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
                self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
                DoorCode.objects.filter(id=code.id).delete()

    def test_a_tracked_slot_whose_readback_gets_no_answer_is_read_back_again(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])
        gateway._get_scripts = {12: _timeouts()}

        self._run_scheduler(gateway)

        code.refresh_from_db()
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", code.last_push_error)
        self.assertEqual(code.push_attempt_count, 1)
        # Nothing recorded, so the retry doesn't clear it blind.
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])

        gateway._lock_codes[(12, 1)] = "9999"  # typed in on the keypad meanwhile
        gateway._cache_codes[(12, 1)] = "9999"
        self._run_scheduler(gateway)

        code.refresh_from_db()
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: "9999"})
        self.assertEqual(self._slots(code), {self.BACK: None})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_a_busy_lock_keeps_the_code_pending(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])

        @contextlib.contextmanager
        def busy(lock_entity_ids, *, deadline=None):
            raise LockBusy(f"Another operation on {self.BACK} is still running. Try again in a moment.")
            yield  # pragma: no cover

        with patch.object(lock_push_uc, "hold_lock_sync", busy):
            successes, failures = lock_push_uc.push_or_settle_after_clear_retry(door_code=code, zwavejs=gateway)

        code.refresh_from_db()
        self.assertEqual(successes, [])
        self.assertEqual([lock for lock, _reason in failures], [self.BACK])
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", code.last_push_error)
        # Nothing was tried there, so it doesn't count toward the cap.
        self.assertEqual(code.push_attempt_count, 0)

    def test_slots_with_a_recorded_failure_are_left_to_the_retry(self):
        # Slot 1 is tracked and slot 2 unconfirmed, both with a failed clear on
        # record. Slot 3 is unconfirmed with nothing recorded, so only it is checked.
        code, gateway = self._turned_off_without_clearing([self.BACK])
        for slot_index in (2, 3):
            lock_push_uc._record_unconfirmed_slot_attempt(
                door_code=code, lock_entity_id=self.BACK, slot_index=slot_index, reason="timeout", pin=self.PIN
            )
            gateway._lock_codes[(12, slot_index)] = self.PIN
        for slot_index, unconfirmed in ((1, False), (2, True)):
            lock_push_uc.record_clear_failure(
                door_code=code,
                lock_entity_id=self.BACK,
                slot_index=slot_index,
                exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
                expected_pin=self.PIN,
                unconfirmed=unconfirmed,
            )

        lock_push_uc.clear_inactive_code_slots(door_code=code, zwavejs=gateway)

        touched = sorted({c["args"][0] for c in gateway.invoke_calls if c["command_class"] == 99})
        self.assertEqual(touched, [3])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN, 2: self.PIN})
        self.assertEqual(sorted(f.slot_index for f in lock_push_uc.unresolved_clear_failures(door_code=code)), [1, 2])

    def test_an_unconfirmed_slot_on_a_lock_thats_gone_is_settled(self):
        code, gateway = self._code_with_side_unconfirmed()
        door_codes_uc.update_door_code(code=code, changes={"is_active": False}, actor_user=self.user)
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=self.BACK).update(slot_index=None)
        Entity.objects.filter(entity_id=self.SIDE).delete()

        self._run_scheduler(gateway)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [])
        self.assertEqual(lock_push_uc.inactive_slots_to_clear(door_code=code), [])
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, DoorCode.PushState.PUSHED)

    def test_an_unconfirmed_slot_whose_lock_goes_away_before_the_clear_is_settled(self):
        code, gateway = self._code_with_side_unconfirmed()
        door_codes_uc.update_door_code(code=code, changes={"is_active": False}, actor_user=self.user)
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=self.BACK).update(slot_index=None)

        # The readback works, then the entity is gone by the time of the clear.
        with patch.object(lock_push_uc, "clear_lock_user_code_slot", side_effect=LockSyncNotFound("Lock not found.")):
            self._run_scheduler(gateway)

        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [])
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, DoorCode.PushState.PUSHED)

    def test_the_scheduler_skips_a_pushed_inactive_code_with_nothing_left(self):
        # An old unconfirmed attempt puts it in the rough cut, but a later push closed its window.
        code, gateway = self._deactivated_code([self.BACK])
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id=self.BACK, slot_index=2, reason="timeout", pin=self.PIN
        )
        DoorCodeEvent.objects.create(
            door_code=code,
            lock_entity_id=self.BACK,
            event_type=DoorCodeEvent.EventType.CODE_SYNCED,
            metadata={"action": "pushed", "slot_index": 1},
        )

        self.assertEqual(self._run_scheduler(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

    def test_a_checked_attempt_newer_than_an_open_failure_is_settled(self):
        # The cleanup checks slot 1 against the newest attempt's PIN, so that check
        # covers the attempt even though the older failure's resolve doesn't.
        code, gateway = self._turned_off_without_clearing([self.BACK])
        DoorCodeLockAssignment.objects.filter(door_code=code).update(slot_index=None)
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=self.BACK,
            slot_index=1,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin="1111",
            unconfirmed=True,
        )
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id=self.BACK, slot_index=1, reason="timeout", pin=self.PIN
        )
        gateway._lock_codes[(12, 1)] = "9999"

        _cleared, failed = lock_push_uc.clear_unconfirmed_slots_holding_pin(
            door_code=code, pin=self.PIN, lock_entity_ids=[self.BACK], zwavejs=gateway
        )

        self.assertEqual(failed, [])
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
        self.assertEqual(lock_push_uc._unconfirmed_attempts(door_code=code, lock_entity_id=self.BACK), {})

    def test_the_scheduler_leaves_a_pending_synced_inactive_code_alone(self):
        code, gateway = self._turned_off_without_clearing([self.BACK])
        DoorCode.objects.filter(id=code.id).update(source=DoorCode.Source.SYNCED, push_state=DoorCode.PushState.PENDING)

        self.assertEqual(self._run_scheduler(gateway), 0)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, DoorCode.PushState.PENDING)
