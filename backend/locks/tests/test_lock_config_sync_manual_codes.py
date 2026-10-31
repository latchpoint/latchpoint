"""Lock config sync and manual door codes (issue #166).

A sync leaves a manual code whose slot holds its PIN manual, and lets a tracked
slot of an active manual code go only when a live readback answers Available
twice, so the scheduler pushes the code again. Kept apart from
``test_lock_config_sync_api`` because it builds on ``test_tracking_integrity``,
which imports that module through ``test_door_code_locking``.
"""

from __future__ import annotations

from unittest.mock import patch

from django.db.models import Model, QuerySet
from django.urls import reverse
from integrations_zwavejs.manager import ZwavejsCommandError
from rest_framework.test import APITestCase

from accounts.models import User
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_tracking_integrity import (
    EMPTY,
    MASKED,
    _Clock,
    _holding,
    _SlowGateway,
    _timeouts,
    _TrackingTestBase,
)
from locks.use_cases import lock_config_sync as lock_config_sync_uc
from locks.use_cases import lock_push as lock_push_uc


class ManualCodeSyncTests(_TrackingTestBase, APITestCase):
    """Issue #166: lock sync leaves manual codes manual and reconciles their empty slots."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)
        self.other = User.objects.create_user(email="other@example.com", password="pass")

    def _sync_for(self, gateway, *, target_user=None, dry_run=False) -> lock_config_sync_uc.SyncResult:
        return lock_config_sync_uc.sync_lock_config(
            lock_entity_id=self.BACK,
            target_user=target_user or self.user,
            actor_user=self.user,
            zwavejs=gateway,
            dry_run=dry_run,
        )

    @staticmethod
    def _row(result: lock_config_sync_uc.SyncResult, slot_index: int) -> lock_config_sync_uc.SlotSyncResult:
        return next(row for row in result.slots if row.slot_index == slot_index)

    def _assignment(self, code: DoorCode) -> DoorCodeLockAssignment:
        return DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.BACK)

    # --- leave manual codes manual ---

    def test_a_manual_code_whose_slot_holds_its_pin_stays_manual_and_editable(self):
        for name, cached in (("readable", self.PIN), ("masked", "****")):
            with self.subTest(slot=name):
                DoorCodeEvent.objects.all().delete()
                DoorCode.objects.all().delete()
                code = self._code(slots={self.BACK: 1}, label="Dog walker")
                # Converted by a sync before #166, which stays synced.
                converted = self._code(pin="9999", source=DoorCode.Source.SYNCED, slots={self.BACK: 2})
                gateway = self._gateway({1: self.PIN, 2: "9999"}, cache={1: cached, 2: "9999"})

                result = self._sync_for(gateway, target_user=self.other)

                row = self._row(result, 1)
                self.assertEqual(row.action, "unchanged")
                self.assertNotIn("owner_changed", row.warnings)
                code.refresh_from_db()
                self.assertEqual(code.source, DoorCode.Source.MANUAL)
                self.assertEqual(code.user_id, self.user.id)
                self.assertTrue(code.is_active)
                self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
                assignment = self._assignment(code)
                self.assertEqual(assignment.slot_index, 1)
                self.assertEqual(assignment.push_state, DoorCode.PushState.PUSHED)
                converted.refresh_from_db()
                self.assertEqual(converted.source, DoorCode.Source.SYNCED)

                # Still editable from the API, PIN included, and the PIN change goes to the lock.
                url = reverse("door-code-detail", args=[code.id])
                with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
                    response = self.client.patch(
                        url, {"label": "Walker", "code": "5555", "reauth_password": "pass"}, format="json"
                    )
                self.assertEqual(response.status_code, 200, response.content)
                self.assertIn("5555", self._lock_codes(gateway, 12).values())
                self.assertNotIn(self.PIN, self._lock_codes(gateway, 12).values())
                self.assertIsNotNone(self._assignment(code).slot_index)

    def test_a_manual_code_disabled_at_the_lock_stays_on_and_is_flagged(self):
        code = self._code(slots={self.BACK: 1})
        gateway = self._gateway({1: self.PIN})
        gateway._slot_status = {1: 2}  # Occupied/Disabled, code not in the cache

        result = self._sync_for(gateway)

        row = self._row(result, 1)
        self.assertEqual(row.action, "unchanged")
        self.assertIn("disabled_on_lock", row.warnings)
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(code.source, DoorCode.Source.MANUAL)
        # The event and the lock's error say so, so the card doesn't just say On lock (PR #214 review).
        event = DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED).latest(
            "id"
        )
        self.assertTrue(event.metadata.get("disabled_on_lock"))
        assignment = self._assignment(code)
        self.assertEqual(assignment.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(assignment.last_push_error, "Slot 1 is disabled at the lock.")

        # Turned back on at the lock, the next sync clears it.
        gateway._slot_status = {}
        gateway._cache_codes[(12, 1)] = self.PIN
        self._sync_for(gateway)
        self.assertEqual(self._assignment(code).last_push_error, "")

    def test_a_dated_manual_code_left_manual_still_retires_off_its_lock(self):
        code, gateway = self._temporary_code([self.BACK])
        self.assertEqual(self._slots(code), {self.BACK: 1})

        self._sync_for(gateway)
        code.refresh_from_db()
        self.assertEqual(code.source, DoorCode.Source.MANUAL)
        self.assertEqual(code.code_type, DoorCode.CodeType.TEMPORARY)

        self._move(code, end_at=self._ago(minutes=1))
        self._enforce(gateway)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})

    # --- an empty tracked slot of a manual code ---

    def test_an_empty_tracked_slot_is_let_go_and_the_scheduler_pushes_the_code_again(self):
        code = self._code(slots={self.BACK: 1})
        gateway = self._gateway()  # the PIN is gone from the lock and the cache

        result = self._sync_for(gateway)

        row = self._row(result, 1)
        self.assertEqual(row.action, "updated")
        self.assertIn("slot_empty_repush", row.warnings)
        self.assertEqual([call[1] for call in self._calls(gateway, "get")], [[1], [1]])
        assignment = self._assignment(code)
        self.assertIsNone(assignment.slot_index)
        self.assertEqual(assignment.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(assignment.push_attempt_count, 0)
        self.assertIn("Slot 1 read back empty", assignment.last_push_error)
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(code.source, DoorCode.Source.MANUAL)
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertTrue(lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=1, door_code=code))
        self.assertTrue(
            DoorCodeEvent.objects.filter(
                door_code=code, metadata__action="slot_released", metadata__slot_index=1
            ).exists()
        )

        self._push_pending(gateway)

        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.slot_index)
        self.assertEqual(assignment.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(list(self._lock_codes(gateway, 12).values()), [self.PIN])
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_a_tracked_slot_the_cache_calls_available_is_kept_unless_the_lock_answers_empty_twice(self):
        for name, script in (
            # A lock that hides its codes still answers Occupied for a slot holding one.
            ("masked", [MASKED]),
            ("holds the pin, the cache is stale", [_holding(self.PIN)]),
            ("empty once, then no answer", [EMPTY, *_timeouts(2)]),
            ("no answer", _timeouts(3)),
        ):
            with self.subTest(readback=name):
                DoorCodeEvent.objects.all().delete()
                DoorCode.objects.all().delete()
                code = self._code(slots={self.BACK: 1})
                gateway = self._gateway({1: self.PIN})  # nothing in the cache, so it reads Available
                gateway._get_scripts = {None: list(script)}

                result = self._sync_for(gateway)

                row = self._row(result, 1)
                self.assertEqual(row.action, "skipped")
                self.assertIn("slot_not_confirmed_empty", row.warnings)
                assignment = self._assignment(code)
                self.assertEqual(assignment.slot_index, 1)
                self.assertEqual(assignment.push_state, DoorCode.PushState.PUSHED)
                self.assertFalse(lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=1))

                # Nothing for the scheduler to push either, so no second copy of the PIN.
                self._push_pending(gateway)
                self.assertEqual(self._calls(gateway, "set"), [])
                self.assertEqual(self._calls(gateway, "clear"), [])
                self.assertEqual(self._assignment(code).slot_index, 1)

    def test_an_empty_tracked_slot_is_kept_by_a_dry_run_an_inactive_code_or_a_clear_outstanding(self):
        cases = (
            ("dry run", {}, True, None),
            ("inactive", {"is_active": False}, False, None),
            ("clear outstanding", {}, False, "clear_outstanding"),
        )
        for name, fields, dry_run, reason in cases:
            with self.subTest(case=name):
                DoorCodeEvent.objects.all().delete()
                DoorCode.objects.all().delete()
                code = self._code(slots={self.BACK: 1}, **fields)
                if reason:
                    lock_push_uc.record_clear_failure(
                        door_code=code,
                        lock_entity_id=self.SIDE,
                        slot_index=2,
                        exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
                        expected_pin=self.PIN,
                    )
                gateway = self._gateway()

                result = self._sync_for(gateway, dry_run=dry_run)

                self.assertEqual(self._calls(gateway, "get"), [])
                self.assertEqual(self._assignment(code).slot_index, 1)
                rows = [row for row in result.slots if row.slot_index == 1]
                if reason:
                    self.assertIn(reason, rows[0].warnings)
                else:
                    self.assertEqual(rows, [])

    def test_the_tracked_slot_readbacks_share_the_syncs_readback_budget(self):
        clock = _Clock()
        other = self._code(pin="5678", push_state=DoorCode.PushState.PENDING)
        self._attempt(other, 3, pin="5678", slot_available=True)
        code = self._code(slots={self.BACK: 1})
        gateway = _SlowGateway(clock)
        gateway._get_scripts = {None: [EMPTY, EMPTY, EMPTY, EMPTY]}

        # The manual code's tracked slot is read first, and its first answer takes the whole 30s.
        with patch.object(lock_push_uc, "_time", clock):
            result = self._sync_for(gateway)

        self.assertEqual(self._calls(gateway, "get"), [(12, [1])])
        self.assertIn("slot_not_confirmed_empty", self._row(result, 1).warnings)
        self.assertEqual(self._assignment(code).slot_index, 1)
        # The untracked attempt slot is left for the next sync.
        self.assertFalse(lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=3))
        self.assertEqual(self._unsettled_slots(other), [3])

    # --- PR #214 review ---

    def test_an_empty_tracked_slot_is_kept_when_the_lock_has_the_pin_in_another_slot(self):
        # Manual 4321 tracks slot 1, which was emptied at the lock, and slot 3 also holds 4321.
        cases = (
            # A #133 copy or a keypad re-entry an older sync imported as synced "Slot 3".
            ("copy imported", self.PIN, True),
            # Not imported yet, this same sync imports it.
            ("copy not imported", self.PIN, False),
            # A lock that hides its codes can only be checked against the imported copy.
            ("masked, copy imported", "****", True),
        )
        for drops_duplicates in (True, False):
            for name, cached, imported in cases:
                with self.subTest(drops_duplicates=drops_duplicates, case=name):
                    DoorCodeEvent.objects.all().delete()
                    DoorCode.objects.all().delete()
                    code = self._code(slots={self.BACK: 1})
                    if imported:
                        self._code(source=DoorCode.Source.SYNCED, slots={self.BACK: 3}, label="Slot 3")
                    gateway = self._gateway({3: self.PIN}, cache={3: cached})
                    gateway._drops_duplicates = drops_duplicates

                    result = self._sync_for(gateway)

                    row = self._row(result, 1)
                    self.assertEqual(row.action, "skipped")
                    self.assertIn("pin_in_another_slot", row.warnings)
                    self.assertNotIn([1], [call[1] for call in self._calls(gateway, "get")])
                    assignment = self._assignment(code)
                    self.assertEqual(assignment.slot_index, 1)
                    self.assertEqual(assignment.push_state, DoorCode.PushState.PUSHED)

                    # So the scheduler doesn't push a second copy, or fail the code on a Yale.
                    self._push_pending(gateway)
                    self.assertEqual(self._calls(gateway, "set"), [])
                    self.assertEqual(self._lock_codes(gateway, 12), {3: self.PIN})
                    code.refresh_from_db()
                    self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_the_slot_empty_marker_comes_before_the_release_so_the_repush_keeps_its_tag(self):
        code = self._code(slots={self.BACK: 1})
        gateway = self._gateway()

        self._sync_for(gateway)

        marker = DoorCodeEvent.objects.get(
            door_code=code, metadata__action="unconfirmed_resolved", metadata__slot_index=1
        )
        released = DoorCodeEvent.objects.get(door_code=code, metadata__action="slot_released")
        self.assertTrue(marker.metadata.get("slot_empty"))
        self.assertLess(marker.id, released.id)

        # The re-push goes into slot 1 (Available, as the sync saw) and none of its readbacks answer.
        gateway._get_scripts = {None: _timeouts(3)}
        self._push_pending(gateway)

        self.assertEqual(self._unsettled_slots(code), [1])
        # Tagged like any push into an Available slot, which a marker after the release would drop.
        self.assertEqual(lock_push_uc._available_attempt_slots(door_code=code, lock_entity_id=self.BACK), {1})

    def test_the_tracked_slot_readbacks_run_before_the_sync_writes_any_row(self):
        code = self._code(slots={self.BACK: 1})
        # A synced code the lock changed the PIN of, so the sync writes its row.
        synced = self._code(pin="1111", source=DoorCode.Source.SYNCED, slots={self.BACK: 2}, label="Slot 2")
        gateway = self._gateway({2: "2222"}, cache={2: "2222"})
        events: list[str] = []
        real_invoke = gateway.invoke_cc_api
        real_select_for_update = QuerySet.select_for_update
        real_update = QuerySet.update
        real_save = Model.save

        def invoke_cc_api(**kwargs):
            if kwargs.get("method_name") == "get":
                events.append("get")
            return real_invoke(**kwargs)

        def select_for_update(queryset, *args, **kwargs):
            events.append("write")
            return real_select_for_update(queryset, *args, **kwargs)

        def update(queryset, *args, **kwargs):
            if queryset.model in (DoorCode, DoorCodeLockAssignment):
                events.append("write")
            return real_update(queryset, *args, **kwargs)

        def save(instance, *args, **kwargs):
            if isinstance(instance, (DoorCode, DoorCodeLockAssignment)):
                events.append("write")
            return real_save(instance, *args, **kwargs)

        gateway.invoke_cc_api = invoke_cc_api
        with (
            patch.object(QuerySet, "select_for_update", select_for_update),
            patch.object(QuerySet, "update", update),
            patch.object(Model, "save", save),
        ):
            result = self._sync_for(gateway)

        self.assertIn("slot_empty_repush", self._row(result, 1).warnings)
        self.assertEqual(self._row(result, 2).action, "updated")
        self.assertEqual(lock_push_uc.decrypt_pin_or_none(DoorCode.objects.get(id=synced.id)), "2222")
        self.assertEqual(events.count("get"), 2)
        last_get = len(events) - 1 - events[::-1].index("get")
        self.assertIn("write", events)
        self.assertLess(last_get, events.index("write"))
        self.assertIsNone(self._assignment(code).slot_index)
