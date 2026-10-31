"""The door code API leftovers: issues #171, #159, #170 and the 404s and validity task test from #189."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from integrations_zwavejs.manager import ZwavejsCommandError
from rest_framework.test import APITestCase

from alarm.crypto import SettingsEncryption
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_lock_push import ClearFailingGateway, FakeGateway
from locks.tests.test_slot_clear_tracking import _SlotClearTestBase
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_push as lock_push_uc


class _ApiTestBase(_SlotClearTestBase, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def _patch_response(self, code: DoorCode, gateway: FakeGateway, body: dict):
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            return self.client.patch(
                reverse("door-code-detail", args=[code.id]), {**body, "reauth_password": "pass"}, format="json"
            )

    def _patch(self, code: DoorCode, gateway: FakeGateway, body: dict) -> dict:
        response = self._patch_response(code, gateway, body)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]

    def _get(self, code: DoorCode) -> dict:
        response = self.client.get(reverse("door-code-detail", args=[code.id]))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]

    def _list(self) -> list[dict]:
        response = self.client.get(reverse("door-codes"))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]

    def _failed_drop_of_side(self) -> tuple[DoorCode, ClearFailingGateway]:
        """A code on Back and Side whose Side was removed while Side's clear kept timing out."""
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {13}
        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK]})
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        gateway.invoke_calls.clear()
        return code, gateway

    @staticmethod
    def _removal(data: dict) -> dict[str, bool]:
        return {a["lock_entity_id"]: a["pending_removal"] for a in data["lock_slot_assignments"]}

    @staticmethod
    def _set_nodes(gateway: FakeGateway) -> list[int]:
        return [node for node, _args in _SlotClearTestBase._calls(gateway, "set")]


class PendingRemovalLockListTests(_ApiTestBase):
    """Issue #171: a lock whose removal is still clearing isn't in lock_entity_ids, so sending that back keeps it."""

    def test_lock_entity_ids_leaves_out_a_lock_being_removed(self):
        code, _gateway = self._failed_drop_of_side()

        for data in (self._get(code), self._list()[0]):
            self.assertEqual(data["lock_entity_ids"], [self.BACK])
            self.assertEqual(self._removal(data), {self.BACK: False, self.SIDE: True})
            self.assertEqual(
                data["pending_slot_clears"], [{"lock_entity_id": self.SIDE, "slot_index": 1, "removing": True}]
            )

    def test_sending_lock_entity_ids_back_unchanged_keeps_the_removal(self):
        code, gateway = self._failed_drop_of_side()
        sent_back = self._get(code)["lock_entity_ids"]

        data = self._patch(code, gateway, {"label": "Renamed", "lock_entity_ids": sent_back})

        self.assertEqual(self._removal(data), {self.BACK: False, self.SIDE: True})
        self.assertEqual(self._set_nodes(gateway), [])

        gateway.clear_fails_on = set()
        self._run_scheduler(gateway)
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(self._lock_codes(gateway, 13), {})


class LockAddRemoveTests(_ApiTestBase):
    """Issue #159: the edit form sends the locks the user added or removed, applied to what the code has now."""

    def test_a_stale_tab_adding_a_lock_doesnt_put_back_one_removed_elsewhere(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        # Another tab removes Side.
        self._patch(code, gateway, {"lock_entity_ids": [self.BACK]})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        gateway.invoke_calls.clear()

        # This tab still shows Back and Side, and the user ticks Front.
        data = self._patch(code, gateway, {"add_lock_entity_ids": [self.FRONT]})

        self.assertEqual(data["lock_entity_ids"], [self.BACK, self.FRONT])
        self.assertEqual(self._slots(code), {self.BACK: 1, self.FRONT: 1})
        self.assertEqual(self._set_nodes(gateway), [14])
        self.assertEqual(self._lock_codes(gateway, 13), {})

    def test_removing_a_lock_leaves_one_added_elsewhere(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        # Another tab adds Front.
        self._patch(code, gateway, {"lock_entity_ids": [self.BACK, self.SIDE, self.FRONT]})

        data = self._patch(code, gateway, {"remove_lock_entity_ids": [self.SIDE]})

        self.assertEqual(data["lock_entity_ids"], [self.BACK, self.FRONT])
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._lock_codes(gateway, 14), {1: self.PIN})

    def test_adding_back_a_lock_being_removed_cancels_the_removal(self):
        code, gateway = self._failed_drop_of_side()

        data = self._patch(code, gateway, {"add_lock_entity_ids": [self.SIDE]})

        self.assertEqual(data["lock_entity_ids"], [self.BACK, self.SIDE])
        self.assertEqual(self._removal(data), {self.BACK: False, self.SIDE: False})

    def test_another_lock_change_leaves_a_pending_removal_going(self):
        code, gateway = self._failed_drop_of_side()

        data = self._patch(code, gateway, {"add_lock_entity_ids": [self.FRONT]})

        self.assertEqual(data["lock_entity_ids"], [self.BACK, self.FRONT])
        self.assertEqual(self._removal(data), {self.BACK: False, self.SIDE: True, self.FRONT: False})
        gateway.clear_fails_on = set()
        self._run_scheduler(gateway)
        self.assertEqual(self._slots(code), {self.BACK: 1, self.FRONT: 1})
        self.assertEqual(self._lock_codes(gateway, 13), {})

    def test_adding_a_lock_the_code_already_has_touches_nothing(self):
        code, gateway = self._failed_drop_of_side()
        updates = DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_UPDATED)
        updates_before = updates.count()

        data = self._patch(code, gateway, {"add_lock_entity_ids": [self.BACK], "remove_lock_entity_ids": []})

        # Side's clear isn't retried and nothing is pushed or recorded.
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._removal(data), {self.BACK: False, self.SIDE: True})
        self.assertEqual(updates.count(), updates_before)

    def test_mixing_the_full_list_with_changes_or_adding_and_removing_a_lock_is_refused(self):
        code, gateway = self._pushed_code([self.BACK])
        bodies = (
            {"lock_entity_ids": [self.BACK], "add_lock_entity_ids": [self.SIDE]},
            {"lock_entity_ids": [self.BACK], "remove_lock_entity_ids": [self.BACK]},
            {"add_lock_entity_ids": [self.SIDE], "remove_lock_entity_ids": [self.SIDE]},
        )
        for body in bodies:
            with self.subTest(body=body):
                response = self._patch_response(code, gateway, body)
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(gateway.invoke_calls, [])

    def test_a_synced_code_cant_add_or_remove_locks(self):
        code = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK, slot_index=1)
        gateway = FakeGateway(usersNumber=5)
        for field in ("add_lock_entity_ids", "remove_lock_entity_ids"):
            with self.subTest(field=field):
                response = self._patch_response(code, gateway, {field: [self.SIDE]})
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(field, response.json()["error"]["details"])


class DeletedMidRequestTests(_ApiTestBase):
    """Issue #189: a code deleted while a request works on it is a 404, not a DoesNotExist 500."""

    def test_retry_on_a_code_deleted_meanwhile_is_a_404(self):
        code, gateway = self._pushed_code([self.BACK])

        def delete_it(*, door_code, **_kwargs):
            DoorCode.objects.filter(id=door_code.id).delete()
            return []

        with (
            patch.object(lock_push_uc, "retry_failed_slot_clears", side_effect=delete_it),
            patch("locks.views.door_codes.default_zwavejs_gateway", gateway),
        ):
            response = self.client.post(reverse("door-code-push", args=[code.id]))

        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(self._set_nodes(gateway), [])

    def test_an_inline_push_of_a_code_deleted_meanwhile_sends_nothing(self):
        code, gateway = self._pushed_code([self.BACK])
        DoorCodeLockAssignment.objects.filter(door_code=code).update(slot_index=None, push_state="pending")
        DoorCode.objects.filter(id=code.id).delete()

        self.assertEqual(
            lock_push_uc.push_door_code_to_assigned_locks(door_code=code, zwavejs=gateway, only_unassigned=True),
            ([], []),
        )
        self.assertEqual(gateway.invoke_calls, [])

    def test_patch_and_create_on_a_code_deleted_meanwhile_are_404s(self):
        code, gateway = self._pushed_code([self.BACK])
        real_update = door_codes_uc.update_door_code
        real_create = door_codes_uc.create_door_code

        def update_then_delete(**kwargs):
            updated = real_update(**kwargs)
            DoorCode.objects.filter(id=updated.id).delete()
            return updated

        def create_then_delete(**kwargs):
            created = real_create(**kwargs)
            DoorCode.objects.filter(id=created.id).delete()
            return created

        with patch.object(door_codes_uc, "update_door_code", side_effect=update_then_delete):
            response = self._patch_response(code, gateway, {"label": "Renamed"})
        self.assertEqual(response.status_code, 404, response.content)

        body = {
            "user_id": str(self.user.id),
            "code": "5678",
            "lock_entity_ids": [self.SIDE],
            "reauth_password": "pass",
        }
        with (
            patch.object(door_codes_uc, "create_door_code", side_effect=create_then_delete),
            patch("locks.views.door_codes.default_zwavejs_gateway", gateway),
        ):
            response = self.client.post(reverse("door-codes"), body, format="json")
        self.assertEqual(response.status_code, 404, response.content)


class ValidityTaskNotStartedQueryTests(_SlotClearTestBase):
    """Issue #189: the not-started pass only looks at unconfirmed attempts on locks the code is still on."""

    def test_an_attempt_on_a_lock_the_code_left_doesnt_pick_it(self):
        from locks.tasks import enforce_door_code_validity

        now = timezone.now()
        for still_on_side in (False, True):
            with self.subTest(still_on_side=still_on_side):
                DoorCode.objects.all().delete()
                code = DoorCode.objects.create(
                    user=self.user,
                    encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
                    pin_length=len(self.PIN),
                    code_type=DoorCode.CodeType.TEMPORARY,
                    start_at=now + timedelta(days=1),
                    end_at=now + timedelta(days=2),
                )
                DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK)
                if still_on_side:
                    DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.SIDE)
                lock_push_uc._record_unconfirmed_slot_attempt(
                    door_code=code, lock_entity_id=self.SIDE, slot_index=3, reason="timed out", pin=self.PIN
                )

                with (
                    patch("locks.use_cases.door_codes.withdraw_door_code", return_value=False) as withdraw,
                    patch("locks.tasks.default_zwavejs_gateway", FakeGateway(usersNumber=5)),
                ):
                    enforce_door_code_validity()

                withdrawn = [c.kwargs["code"].id for c in withdraw.call_args_list]
                self.assertEqual(withdrawn, [code.id] if still_on_side else [])


class DoorCodeListQueriesTests(_ApiTestBase):
    """Issue #170: the list endpoint loads the pending clear events once per page, not per code."""

    # The codes, their assignments and the clear and attempt events. With an
    # inactive manual code on the page, the last push per lock and the slots
    # held on those locks too. The attempt cap is one more, only read when some
    # lock has a queued push (#206).
    INACTIVE_PAGE_QUERIES = 5
    QUEUED_ACTIVE_PAGE_QUERIES = 4
    MIXED_PAGE_QUERIES = 6

    def _code(self, *, is_active: bool = True, source: str = DoorCode.Source.MANUAL) -> DoorCode:
        return DoorCode.objects.create(
            user=self.user,
            source=source,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=is_active,
        )

    def _assign(self, code: DoorCode, lock_entity_id: str, slot_index: int | None = None, **fields):
        return DoorCodeLockAssignment.objects.create(
            door_code=code, lock_entity_id=lock_entity_id, slot_index=slot_index, **fields
        )

    def _clear_failed(self, code: DoorCode, lock_entity_id: str, slot_index: int, *, removing: bool = False):
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin=self.PIN,
            removing=removing,
        )

    def _attempt(self, code: DoorCode, lock_entity_id: str, slot_index: int):
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id=lock_entity_id, slot_index=slot_index, reason="timed out", pin=self.PIN
        )

    def _heavy_inactive_code(self, n: int) -> DoorCode:
        """Inactive with a tracked slot, a lock being removed and an unconfirmed attempt, the worst case per code."""
        code = self._code(is_active=False)
        self._assign(code, self.BACK, 10 + n)
        self._assign(code, self.SIDE, 10 + n)
        self._clear_failed(code, self.SIDE, 10 + n, removing=True)
        self._assign(code, self.FRONT)
        self._attempt(code, self.FRONT, 40 + n)
        return code

    def _queued_active_code(self, n: int) -> DoorCode:
        code = self._code()
        self._assign(code, self.BACK, 30 + n, push_state=DoorCode.PushState.PUSHED)
        self._assign(code, self.SIDE, push_requested_at=timezone.now())
        self._clear_failed(code, self.BACK, 60 + n)
        return code

    def _list_queries(self) -> int:
        with CaptureQueriesContext(connection) as queries:
            self._list()
        return len(queries)

    def test_1_3_and_10_codes_cost_the_same_queries(self):
        kinds = (
            (self._heavy_inactive_code, self.INACTIVE_PAGE_QUERIES),
            (self._queued_active_code, self.QUEUED_ACTIVE_PAGE_QUERIES),
        )
        for make, queries in kinds:
            for count in (1, 3, 10):
                with self.subTest(kind=make.__name__, codes=count):
                    DoorCode.objects.all().delete()
                    for n in range(count):
                        make(n)
                    with self.assertNumQueries(queries):
                        data = self._list()
                    self.assertEqual(len(data), count)

    def test_a_mixed_page_costs_the_same_as_a_small_one(self):
        self._heavy_inactive_code(0)
        self._queued_active_code(0)
        small = self._list_queries()
        for n in range(1, 5):
            self._heavy_inactive_code(n)
            self._queued_active_code(n)
        self.assertEqual(self._list_queries(), small)
        self.assertEqual(small, self.MIXED_PAGE_QUERIES)

    def test_the_list_says_what_the_detail_says(self):
        # Every case the per-code fields cover, so the prefetched rules can't
        # drift from the per-code ones without a failure.
        removing = self._code()
        self._assign(removing, self.BACK, 1, push_state=DoorCode.PushState.PUSHED)
        self._assign(removing, self.SIDE, 1)
        self._clear_failed(removing, self.SIDE, 1, removing=True)

        tracked_and_attempt = self._code(is_active=False)
        self._assign(tracked_and_attempt, self.BACK, 2)
        self._assign(tracked_and_attempt, self.FRONT)
        self._attempt(tracked_and_attempt, self.FRONT, 5)

        settled_attempt = self._code(is_active=False)
        self._assign(settled_attempt, self.SIDE)
        self._attempt(settled_attempt, self.SIDE, 6)
        lock_push_uc._settle_unconfirmed_slot(
            door_code=settled_attempt, lock_entity_id=self.SIDE, slot_index=6, outcome="cleared"
        )

        claimed_attempt = self._code(is_active=False)
        self._assign(claimed_attempt, self.BACK)
        self._attempt(claimed_attempt, self.BACK, 1)  # removing tracks Back slot 1

        pushed_since = self._code(is_active=False)
        self._assign(pushed_since, self.FRONT)
        self._attempt(pushed_since, self.FRONT, 7)
        DoorCodeEvent.objects.create(
            door_code=pushed_since,
            user=self.user,
            lock_entity_id=self.FRONT,
            event_type=DoorCodeEvent.EventType.CODE_SYNCED,
            metadata={"action": "pushed", "slot_index": 8},
        )

        failed_then_resolved = self._code(is_active=False)
        self._assign(failed_then_resolved, self.SIDE, 3)
        self._clear_failed(failed_then_resolved, self.SIDE, 9)
        lock_push_uc.resolve_clear_failure(
            door_code=failed_then_resolved, lock_entity_id=self.SIDE, slot_index=9, outcome="cleared"
        )

        failed_open = self._code(is_active=False)
        self._assign(failed_open, self.FRONT, 4)
        self._clear_failed(failed_open, self.FRONT, 4)

        synced_off = self._code(is_active=False, source=DoorCode.Source.SYNCED)
        self._assign(synced_off, self.SIDE, 11)
        self._attempt(synced_off, self.SIDE, 12)

        queued = self._queued_active_code(0)

        listed = {entry["id"]: entry for entry in self._list()}
        codes = (
            removing,
            tracked_and_attempt,
            settled_attempt,
            claimed_attempt,
            pushed_since,
            failed_then_resolved,
            failed_open,
            synced_off,
            queued,
        )
        self.assertEqual(set(listed), {code.id for code in codes})
        for code in codes:
            with self.subTest(code=code.id):
                detail = self._get(code)
                for field in ("lock_entity_ids", "lock_slot_assignments", "pending_slot_clears", "push_state"):
                    self.assertEqual(listed[code.id][field], detail[field], field)

        # And the cases came out the way they're meant to.
        self.assertEqual(listed[removing.id]["lock_entity_ids"], [self.BACK])
        self.assertEqual(
            listed[tracked_and_attempt.id]["pending_slot_clears"],
            [
                {"lock_entity_id": self.BACK, "slot_index": 2, "removing": False},
                {"lock_entity_id": self.FRONT, "slot_index": 5, "removing": False},
            ],
        )
        for code in (settled_attempt, claimed_attempt, pushed_since, synced_off):
            self.assertEqual(listed[code.id]["pending_slot_clears"], [], code.id)
        self.assertEqual(
            listed[failed_then_resolved.id]["pending_slot_clears"],
            [{"lock_entity_id": self.SIDE, "slot_index": 3, "removing": False}],
        )
        self.assertEqual(
            listed[failed_open.id]["pending_slot_clears"],
            [{"lock_entity_id": self.FRONT, "slot_index": 4, "removing": False}],
        )
        queued_entries = {a["lock_entity_id"]: a["push_queued"] for a in listed[queued.id]["lock_slot_assignments"]}
        self.assertEqual(queued_entries, {self.BACK: False, self.SIDE: True})


class LockChangeEdgeTests(_ApiTestBase):
    """PR #213 review: empty lock sets, #188 with added locks, and saves racing other saves or a delete."""

    OTHER_PIN_HOLDER_SLOT = 5

    def _code(self, *, is_active: bool = True) -> DoorCode:
        return DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=is_active,
        )

    def _same_pin_on(self, lock_entity_id: str) -> DoorCode:
        """Another code with this PIN in a slot on ``lock_entity_id``, ie a keypad code lock sync imported."""
        other = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            label="Slot 5",
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
        )
        DoorCodeLockAssignment.objects.create(
            door_code=other, lock_entity_id=lock_entity_id, slot_index=self.OTHER_PIN_HOLDER_SLOT
        )
        return other

    def test_removing_the_last_lock_is_refused(self):
        code, gateway = self._pushed_code([self.BACK])

        response = self._patch_response(code, gateway, {"remove_lock_entity_ids": [self.BACK]})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["error"]["message"], "This save would leave the code with no locks.")
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(gateway.invoke_calls, [])

    def test_a_lock_being_removed_doesnt_count_as_one_left(self):
        code, gateway = self._failed_drop_of_side()

        response = self._patch_response(code, gateway, {"remove_lock_entity_ids": [self.BACK]})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})

    def test_a_full_empty_lock_list_is_still_taken(self):
        code, gateway = self._pushed_code([self.BACK])

        data = self._patch(code, gateway, {"lock_entity_ids": []})

        self.assertEqual(data["lock_entity_ids"], [])
        self.assertEqual(self._lock_codes(gateway, 12), {})

    def test_turning_on_with_an_added_lock_that_has_the_pin_is_refused(self):
        # Issue #188 through add_lock_entity_ids: Side gets added in the same save.
        code = self._code(is_active=False)
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK)
        other = self._same_pin_on(self.SIDE)
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True)

        response = self._patch_response(code, gateway, {"is_active": True, "add_lock_entity_ids": [self.SIDE]})

        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn(f"door code {other.id}", response.json()["error"]["message"])
        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(self._slots(code), {self.BACK: None})
        self.assertEqual(self._set_nodes(gateway), [])

    def test_turning_on_ignores_the_pin_on_a_lock_still_being_removed(self):
        # The push doesn't go to a lock being removed, so a code holding the PIN
        # there isn't a second copy.
        code = self._code(is_active=False)
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK)
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.SIDE, slot_index=2)
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=self.SIDE,
            slot_index=2,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin=self.PIN,
            removing=True,
        )
        self._same_pin_on(self.SIDE)
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True)
        gateway.clear_fails_on = {13}

        data = self._patch(code, gateway, {"is_active": True})

        self.assertTrue(data["is_active"])
        self.assertEqual(self._set_nodes(gateway), [12])
        self.assertEqual(self._removal(data), {self.BACK: False, self.SIDE: True})

    def test_a_lock_another_save_added_meanwhile_isnt_dropped(self):
        # Two adds on a code with no locks hold different lock_sync: locks, so
        # they can run side by side. The other save's lock lands while this one runs.
        code = self._code()
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True)
        real_check = door_codes_uc._refuse_duplicate_pin_when_turning_on

        def other_save_lands(**kwargs):
            if not DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=self.BACK).exists():
                DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK)
            return real_check(**kwargs)

        with patch.object(door_codes_uc, "_refuse_duplicate_pin_when_turning_on", side_effect=other_save_lands):
            data = self._patch(code, gateway, {"add_lock_entity_ids": [self.SIDE]})

        self.assertEqual(data["lock_entity_ids"], [self.BACK, self.SIDE])

    def test_a_save_on_a_code_deleted_meanwhile_is_a_404_and_doesnt_bring_it_back(self):
        code, gateway = self._pushed_code([self.BACK])

        def delete_it(**_kwargs):
            DoorCode.objects.filter(id=code.id).delete()

        with patch.object(door_codes_uc, "_refuse_duplicate_pin_when_turning_on", side_effect=delete_it):
            response = self._patch_response(code, gateway, {"label": "Renamed"})

        self.assertEqual(response.status_code, 404, response.content)
        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
