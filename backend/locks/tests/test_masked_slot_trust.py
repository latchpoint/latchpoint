"""Masked slot trust leftovers from the #193 review (issue #194).

Each class is one of the issue's items. Like ``test_tracking_integrity``, what
these add is reached through the module inside each test, so on a branch
without it each test fails on its own.
"""

from __future__ import annotations

from unittest.mock import patch

from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_tracking_integrity import EMPTY, MASKED, _Clock, _SlowGateway, _timeouts, _TrackingTestBase
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.lock_push import LockUnreachable, push_door_code_to_lock


class _MaskedSlotTrustTestBase(_TrackingTestBase):
    def _settle_empty(self, code: DoorCode, slot: int) -> None:
        lock_push_uc._settle_unconfirmed_slot(
            door_code=code, lock_entity_id=self.BACK, slot_index=slot, outcome="not_holding_pin", slot_empty=True
        )

    def _available(self, code: DoorCode) -> set[int]:
        return lock_push_uc._available_attempt_slots(door_code=code, lock_entity_id=self.BACK)

    def _newest_attempt(self, code: DoorCode) -> dict:
        return (
            DoorCodeEvent.objects.filter(door_code=code, metadata__action="push_unconfirmed")
            .order_by("-id")
            .values_list("metadata", flat=True)
            .first()
        )

    def _push(self, code: DoorCode, gateway) -> None:
        push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)


class SettledSlotEmptyMarkerRetentionTests(_MaskedSlotTrustTestBase):
    """Item 1: a ``slot_empty`` marker that settled the attempts on its slot and then aged out."""

    def test_a_new_pick_of_the_slot_after_retention_is_not_tagged(self):
        code = self._code(push_state=DoorCode.PushState.PENDING)
        self._attempt(code, 2, slot_available=True)
        self._settle_empty(code, 2)
        # Nothing is unsettled on the slot any more.
        self.assertEqual(self._unsettled_slots(code), [])

        self._run_retention(DoorCodeEvent.objects.filter(door_code=code))

        self.assertTrue(lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=2, door_code=code))
        self.assertNotIn("slot_available", self._attempt(code, 2, slot_available=True).metadata)

    def test_a_slot_empty_marker_from_before_the_codes_last_push_there_still_ages_out(self):
        code = self._code(push_state=DoorCode.PushState.PENDING)
        self._attempt(code, 2, slot_available=True)
        self._settle_empty(code, 2)
        DoorCodeEvent.objects.create(
            door_code=code,
            user=self.user,
            lock_entity_id=self.BACK,
            event_type=DoorCodeEvent.EventType.CODE_SYNCED,
            metadata={"action": "pushed", "slot_index": 2},
        )

        self._run_retention(DoorCodeEvent.objects.filter(door_code=code))

        self.assertFalse(lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=2))

    def test_only_the_newest_marker_per_slot_is_kept(self):
        code = self._code(push_state=DoorCode.PushState.PENDING)
        for _ in range(3):
            self._attempt(code, 2, slot_available=True)
            self._settle_empty(code, 2)
        newest = lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=2, door_code=code)[-1]

        self._run_retention(DoorCodeEvent.objects.filter(door_code=code))

        self.assertEqual(
            lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=2, door_code=code), [newest]
        )


class LockSyncSlotEmptyMarkerTests(_MaskedSlotTrustTestBase):
    """Item 2: lock sync reading an untracked slot with an unsettled attempt on it, from a cache that can be stale."""

    def test_a_sync_that_reads_the_slot_empty_disproves_the_attempt_after_retention_too(self):
        code = self._code(push_state=DoorCode.PushState.PENDING)
        self._attempt(code, 3, slot_available=True)
        # The cache says Available and so does the lock.
        gateway = self._gateway()

        self._sync(gateway)

        self.assertEqual([args for _node, args in self._calls(gateway, "get")], [[3], [3]])
        self.assertEqual(self._unsettled_slots(code), [])
        self.assertTrue(lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=3, door_code=code))
        self.assertNotIn("slot_available", self._attempt(code, 3, slot_available=True).metadata)

        DoorCodeEvent.objects.filter(door_code=code, metadata__action="push_unconfirmed").delete()
        self._run_retention(DoorCodeEvent.objects.filter(door_code=code))

        self.assertNotIn("slot_available", self._attempt(code, 3, slot_available=True).metadata)

    def test_a_stale_available_cache_over_a_masked_keypad_code_records_nothing(self):
        code = self._code(push_state=DoorCode.PushState.PENDING)
        self._attempt(code, 3, slot_available=True)
        # A keypad code typed in after the attempt that the cache never heard about.
        gateway = self._gateway({3: "9999"})
        gateway._get_scripts = {None: [MASKED]}

        self._sync(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {3: "9999"})
        self.assertFalse(lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=3))
        self.assertEqual(self._unsettled_slots(code), [3])
        self.assertEqual(self._available(code), {3})

    def test_a_stale_available_cache_and_an_empty_answer_then_silence_drops_the_trust(self):
        code = self._code(push_state=DoorCode.PushState.PENDING)
        self._attempt(code, 3, slot_available=True)
        gateway = self._gateway()
        gateway._get_scripts = {None: [EMPTY, *_timeouts(2)]}

        self._sync(gateway)

        # No verdict, so the attempt stays, but it isn't trusted on a masked readback.
        self.assertEqual(self._unsettled_slots(code), [3])
        self.assertEqual(self._available(code), set())
        self._run_retention(DoorCodeEvent.objects.filter(door_code=code))
        self.assertEqual(self._unsettled_slots(code), [3])
        self.assertEqual(self._available(code), set())

    def test_a_keypad_code_typed_in_after_the_sync_saw_the_slot_empty_is_left_alone_by_the_next_push(self):
        code = self._code(push_state=DoorCode.PushState.PENDING)
        self._attempt(code, 1, slot_available=True)
        gateway = self._gateway()
        self._sync(gateway)
        self.assertEqual(self._unsettled_slots(code), [])

        # Typed in at the keypad; the cache still says slot 1 is Available.
        gateway._lock_codes[(12, 1)] = "9999"
        gateway._get_scripts = {None: [MASKED]}
        gateway.invoke_calls.clear()

        self._push(code, gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: "9999", 2: self.PIN})
        self.assertEqual(self._slots(code), {self.BACK: 2})


class FreshReadBeforeSetTests(_MaskedSlotTrustTestBase):
    """Item 3: the slot the value cache calls Available is read once live before the ``set``."""

    def _pending_code(self) -> DoorCode:
        return self._code(push_state=DoorCode.PushState.PENDING)

    def _ops(self, gateway) -> list[tuple[str, int]]:
        return [
            (c["method_name"], c["args"][0])
            for c in gateway.invoke_calls
            if c["command_class"] == 99 and c["method_name"] in {"get", "set", "clear"}
        ]

    def test_a_slot_the_cache_calls_available_that_holds_a_keypad_code_is_not_written_over(self):
        for name, answer in (("masked", MASKED), ("readable", {"userIdStatus": 1, "userCode": "9999"})):
            with self.subTest(keypad_code=name):
                DoorCodeEvent.objects.all().delete()
                DoorCode.objects.all().delete()
                code = self._pending_code()
                gateway = self._gateway({1: "9999"})
                gateway._get_scripts = {None: [answer]}

                self._push(code, gateway)

                self.assertEqual(self._lock_codes(gateway, 12), {1: "9999", 2: self.PIN})
                self.assertEqual(self._slots(code), {self.BACK: 2})
                # One get before the set, none for the second pick.
                self.assertEqual(self._ops(gateway), [("get", 1), ("set", 2), ("get", 2)])

    def test_a_lock_config_slot_the_cache_calls_available_is_skipped(self):
        code = self._pending_code()
        gateway = self._gateway()
        gateway._get_scripts = {None: [{"userIdStatus": 3, "userCode": ""}]}

        self._push(code, gateway)

        self.assertEqual(self._slots(code), {self.BACK: 2})
        self.assertEqual(self._ops(gateway), [("get", 1), ("set", 2), ("get", 2)])

    def test_an_available_answer_keeps_the_slot_available_tag_on_a_readback_timeout(self):
        code = self._pending_code()
        gateway = self._gateway()
        gateway._get_scripts = {None: [EMPTY, *_timeouts(3)]}

        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)

        self.assertEqual(self._ops(gateway), [("get", 1), ("set", 1), ("get", 1), ("get", 1), ("get", 1)])
        self.assertIs(self._newest_attempt(code).get("slot_available"), True)

    def test_no_answer_before_the_set_sends_nothing_and_counts_like_a_set_that_timed_out(self):
        for name, answer in (
            ("timeout", _timeouts(1)[0]),
            ("status not available", {"userIdStatus": 254, "userCode": ""}),
            ("no report", None),
        ):
            with self.subTest(fresh_read=name):
                DoorCodeEvent.objects.all().delete()
                DoorCode.objects.all().delete()
                code = self._pending_code()
                gateway = self._gateway()
                gateway._get_scripts = {None: [answer]}

                with self.assertRaises(LockUnreachable):
                    self._push(code, gateway)

                # Nothing goes out after it (issue #199), and nothing is on record for the slot.
                self.assertEqual(self._ops(gateway), [("get", 1)])
                self.assertEqual(self._lock_codes(gateway, 12), {})
                self.assertIsNone(self._newest_attempt(code))
                assignment = DoorCodeLockAssignment.objects.get(door_code=code)
                self.assertEqual(
                    (assignment.slot_index, assignment.push_state, assignment.push_attempt_count),
                    (None, DoorCode.PushState.PENDING, 1),
                )

    def test_a_lock_that_never_answers_the_read_fails_at_the_attempt_cap(self):
        code = self._pending_code()
        DoorCodeLockAssignment.objects.filter(door_code=code).update(push_attempt_count=23)
        gateway = self._gateway()
        gateway._get_scripts = {None: _timeouts(1)}

        self._push_pending(gateway)

        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual(self._ops(gateway), [("get", 1)])
        self.assertEqual(assignment.push_attempt_count, 24)
        self.assertEqual(assignment.push_state, DoorCode.PushState.FAILED)

    def test_the_second_pick_after_an_occupied_answer_is_not_tagged(self):
        code = self._pending_code()
        gateway = self._gateway({1: "9999"})
        gateway._get_scripts = {None: [MASKED, *_timeouts(3)]}

        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)

        self.assertEqual(self._ops(gateway)[:2], [("get", 1), ("set", 2)])
        marker = self._newest_attempt(code)
        self.assertEqual(marker["slot_index"], 2)
        self.assertNotIn("slot_available", marker)
        self.assertEqual(self._lock_codes(gateway, 12), {1: "9999", 2: self.PIN})

    def test_a_read_that_uses_up_the_push_budget_sends_nothing(self):
        clock = _Clock()
        code = self._pending_code()
        gateway = _SlowGateway(clock)

        with patch.object(lock_push_uc, "_time", clock), self.assertRaises(LockUnreachable):
            self._push(code, lock_push_uc.BudgetedGateway(gateway, seconds=30.0))

        self.assertEqual(self._ops(gateway), [("get", 1)])
        self.assertIsNone(self._newest_attempt(code))
        # Out of time isn't counted toward door_codes.push_max_attempts.
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=code).push_attempt_count, 0)

    def test_a_push_that_adopts_its_attempt_slot_reads_nothing_extra(self):
        code = self._pending_code()
        self._attempt(code, 2)
        gateway = self._gateway({2: self.PIN})

        self._push(code, gateway)

        self.assertEqual(self._slots(code), {self.BACK: 2})
        self.assertEqual(self._ops(gateway), [("get", 2)])


class DeletedCodeSlotEmptyMarkerTests(_MaskedSlotTrustTestBase):
    """Item 4 (from #212): deleting a code used to cascade its ``slot_empty`` markers away."""

    def _other_code_saw_the_slot_empty(self) -> tuple[DoorCode, DoorCode]:
        code = self._code(push_state=DoorCode.PushState.PENDING)
        self._attempt(code, 2, slot_available=True)
        self.assertEqual(self._available(code), {2})
        other = self._code(pin="5555", push_state=DoorCode.PushState.PENDING)
        self._attempt(other, 2, pin="5555")
        self._settle_empty(other, 2)
        self.assertEqual(self._available(code), set())
        return code, other

    def test_deleting_the_other_code_keeps_its_empty_readback_counting(self):
        code, other = self._other_code_saw_the_slot_empty()

        door_codes_uc.delete_door_code(code=other, actor_user=self.user, zwavejs=self._gateway())

        self.assertFalse(DoorCode.objects.filter(id=other.id).exists())
        self.assertEqual(self._available(code), set())
        # Only the slot_empty markers outlive it.
        self.assertFalse(
            DoorCodeEvent.objects.filter(door_code__isnull=True, metadata__action="push_unconfirmed").exists()
        )

    def test_retention_keeps_the_deleted_codes_marker_while_the_tagged_attempt_is_kept(self):
        code, other = self._other_code_saw_the_slot_empty()
        door_codes_uc.delete_door_code(code=other, actor_user=self.user, zwavejs=self._gateway())

        self._run_retention(DoorCodeEvent.objects.all())

        self.assertEqual(self._unsettled_slots(code), [2])
        self.assertEqual(self._available(code), set())

    def test_a_deleted_codes_marker_with_no_tagged_record_after_it_ages_out(self):
        _code, other = self._other_code_saw_the_slot_empty()
        DoorCodeEvent.objects.filter(door_code=_code).delete()
        door_codes_uc.delete_door_code(code=other, actor_user=self.user, zwavejs=self._gateway())

        self._run_retention(DoorCodeEvent.objects.all())

        self.assertFalse(lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=2))
