"""Slot and PIN tracking integrity leftovers (issues #175, #180, #185, #188, #194 and the #207 review).

Like ``test_door_code_lifecycle``, what these add is reached through the module
inside each test, so on a branch without it each test fails on its own.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from integrations_zwavejs.manager import ZwavejsCommandError
from rest_framework.test import APITestCase

from alarm.crypto import SettingsEncryption
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_door_code_lifecycle import _LifecycleTestBase
from locks.tests.test_lock_push import ClearFailingGateway
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_config_sync as lock_config_sync_uc
from locks.use_cases import lock_push as lock_push_uc

EMPTY = {"userIdStatus": 0, "userCode": ""}
MASKED = {"userIdStatus": 1, "userCode": "****"}


def _timeouts(count: int = 3) -> list[Exception]:
    return [ZwavejsCommandError("driver TimeoutError after 5.0s") for _ in range(count)]


def _holding(pin: str) -> dict:
    return {"userIdStatus": 1, "userCode": pin}


class _TrackingTestBase(_LifecycleTestBase):
    def _code(
        self,
        *,
        pin: str | None = None,
        source: str = DoorCode.Source.MANUAL,
        is_active: bool = True,
        slots: dict[str, int | None] | None = None,
        **fields,
    ) -> DoorCode:
        """A code row with assignments, without any push (the slots are set as given)."""
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=fields.pop("encrypted_pin", None) or SettingsEncryption.get().encrypt(pin or self.PIN),
            pin_length=len(pin or self.PIN),
            code_type=fields.pop("code_type", DoorCode.CodeType.PERMANENT),
            source=source,
            is_active=is_active,
            push_state=fields.pop("push_state", DoorCode.PushState.PUSHED),
            **fields,
        )
        for lock_entity_id, slot_index in (slots or {self.BACK: None}).items():
            DoorCodeLockAssignment.objects.create(
                door_code=code,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                push_state=DoorCode.PushState.PUSHED if slot_index is not None else DoorCode.PushState.PENDING,
            )
        return code

    @staticmethod
    def _gateway(lock: dict[int, str] | None = None, *, cache: dict[int, str] | None = None) -> ClearFailingGateway:
        """Node 12 holding ``lock`` (slot -> PIN), with ``cache`` in the Z-Wave JS value cache."""
        gateway = ClearFailingGateway(usersNumber=5)
        for slot, pin in (lock or {}).items():
            gateway._lock_codes[(12, slot)] = pin
        for slot, pin in (cache or {}).items():
            gateway._cache_codes[(12, slot)] = pin
        return gateway

    def _attempt(self, code: DoorCode, slot: int, *, pin: str | None = None, **tags) -> DoorCodeEvent:
        return lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code,
            lock_entity_id=self.BACK,
            slot_index=slot,
            reason="driver TimeoutError after 5.0s",
            pin=pin or self.PIN,
            **tags,
        )

    @staticmethod
    def _run_retention(events) -> None:
        from locks.tasks import cleanup_door_code_events

        events.update(created_at=timezone.now() - timedelta(days=91))
        with patch("locks.tasks._get_door_code_event_retention_days", return_value=90):
            cleanup_door_code_events()

    def _unsettled_slots(self, code: DoorCode) -> list[int]:
        return lock_push_uc._unconfirmed_attempt_slots(door_code=code, lock_entity_id=self.BACK)

    def _sync(self, gateway: ClearFailingGateway) -> lock_config_sync_uc.SyncResult:
        return lock_config_sync_uc.sync_lock_config(
            lock_entity_id=self.BACK, target_user=self.user, actor_user=self.user, zwavejs=gateway
        )


class RetentionOpenFailureTests(_TrackingTestBase):
    """Issue #175: retention and the start of a clear failure that's still open."""

    def test_retention_keeps_the_start_of_an_open_failure_so_a_later_attempt_stays_tracked(self):
        # The #167 review's repro: a clear failure expecting 1111 on slot 1, then an
        # unconfirmed push of 4321 into slot 1, then the failure is re-recorded.
        code = self._code(pin=self.PIN)
        gateway = self._gateway({1: self.PIN})
        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        lock_push_uc.record_clear_failure(
            door_code=code, lock_entity_id=self.BACK, slot_index=1, exc=timeout, expected_pin="1111", unconfirmed=True
        )
        attempt = self._attempt(code, 1)
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=self.BACK,
            slot_index=1,
            exc=timeout,
            expected_pin="1111",
            unconfirmed=True,
            removing=True,
        )
        self.assertEqual(DoorCodeEvent.objects.filter(door_code=code, metadata__action="clear_failed").count(), 2)

        self._run_retention(DoorCodeEvent.objects.filter(door_code=code))

        # Both of the open failure's events and the attempt are kept.
        self.assertEqual(DoorCodeEvent.objects.filter(door_code=code, metadata__action="clear_failed").count(), 2)
        self.assertTrue(DoorCodeEvent.objects.filter(id=attempt.id).exists())

        # Retry finds 4321 where it expected 1111, which only says 1111 isn't there.
        lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=gateway)

        self.assertEqual(self._unsettled_slots(code), [1])
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [self.BACK])
        # So deleting the code still reads slot 1 back and clears 4321.
        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)
        self.assertEqual(self._lock_codes(gateway, 12), {})

    def test_a_non_emptied_resolve_whose_failure_was_pruned_settles_nothing(self):
        code = self._code(pin=self.PIN)
        failure = lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=self.BACK,
            slot_index=1,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin="1111",
            unconfirmed=True,
        )
        self.assertFalse(failure.permanent)
        failed_event = DoorCodeEvent.objects.get(door_code=code, metadata__action="clear_failed")
        attempt = self._attempt(code, 1)
        lock_push_uc.resolve_clear_failure(
            door_code=code, lock_entity_id=self.BACK, slot_index=1, outcome="not_holding_pin"
        )

        # Only the failure is old enough to go, and it's settled.
        self._run_retention(DoorCodeEvent.objects.filter(id=failed_event.id))

        self.assertFalse(DoorCodeEvent.objects.filter(id=failed_event.id).exists())
        # The resolve only said 1111 wasn't there, so the attempt after the failure still counts.
        self.assertEqual(
            {
                slot: event_id
                for slot, (event_id, _metadata) in lock_push_uc._unsettled_unconfirmed_attempts(
                    door_code=code, lock_entity_id=self.BACK
                ).items()
            },
            {1: attempt.id},
        )

    def test_a_tracked_slot_of_a_code_whose_pin_cannot_be_read_is_cleared_not_forgotten(self):
        code = self._code(encrypted_pin="not-used-here", is_active=False, slots={self.BACK: 2})
        gateway = self._gateway({2: "9999"})

        still_failing = lock_push_uc.clear_inactive_code_slots(door_code=code, zwavejs=gateway)

        self.assertEqual(still_failing, [])
        # No PIN to compare against, so no readback, and the slot counts as its own.
        self.assertEqual(self._calls(gateway, "get"), [])
        self.assertEqual(self._calls(gateway, "clear"), [(12, [2])])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None})
        resolved = DoorCodeEvent.objects.filter(door_code=code, metadata__action="clear_resolved")
        self.assertFalse(resolved.exclude(metadata__outcome="cleared").exists())


class SyncedAttemptReconcileTests(_TrackingTestBase):
    """Issue #180: a synced code's open attempt on its own lock gets a read-only readback."""

    def _synced_code_with_attempt(self, slot_two: dict | None, **tags) -> tuple[DoorCode, ClearFailingGateway]:
        code = self._code(source=DoorCode.Source.SYNCED, slots={self.BACK: 1})
        self._attempt(code, 2, **tags)
        gateway = self._gateway({1: self.PIN}, cache={1: self.PIN})
        gateway._get_scripts = {None: [slot_two] if slot_two is not None else []}
        return code, gateway

    def _sync_row(self, gateway: ClearFailingGateway, slot: int):
        return next(row for row in self._sync(gateway).slots if row.slot_index == slot)

    def test_an_attempt_slot_that_does_not_hold_the_pin_is_settled_and_lock_sync_reconciles_the_code(self):
        for name, slot_two, slot_empty in (
            ("empty", EMPTY, True),
            ("different code", _holding("9999"), False),
            ("masked, untagged", MASKED, False),
        ):
            with self.subTest(slot_two=name):
                DoorCodeEvent.objects.all().delete()
                DoorCode.objects.all().delete()
                code, gateway = self._synced_code_with_attempt(slot_two)
                # Lock sync skips it while the attempt is open.
                self.assertTrue(
                    lock_config_sync_uc._has_outstanding_slot_cleanup(door_code=code, lock_entity_id=self.BACK)
                )

                self._push_pending(gateway)

                self.assertEqual(self._unsettled_slots(code), [])
                # Read only: nothing set or cleared.
                self.assertEqual([c["method_name"] for c in gateway.invoke_calls], ["get"] * len(gateway.invoke_calls))
                marker = DoorCodeEvent.objects.filter(door_code=code, metadata__action="unconfirmed_resolved").get()
                self.assertEqual(marker.metadata["outcome"], "not_holding_pin")
                self.assertEqual(bool(marker.metadata.get("slot_empty")), slot_empty)
                # The next lock sync reconciles the code instead of skipping it.
                row = self._sync_row(gateway, 1)
                self.assertEqual(row.action, "updated")
                self.assertNotIn("clear_outstanding", row.warnings)

    def test_an_attempt_slot_that_may_hold_the_pin_is_left_alone(self):
        for name, slot_two, tags in (
            ("its pin", _holding(self.PIN), {}),
            ("masked, slot_available", MASKED, {"slot_available": True}),
        ):
            with self.subTest(slot_two=name):
                DoorCodeEvent.objects.all().delete()
                DoorCode.objects.all().delete()
                code, gateway = self._synced_code_with_attempt(slot_two, **tags)

                self._push_pending(gateway)

                self.assertEqual(self._unsettled_slots(code), [2])
                self.assertEqual(self._calls(gateway, "clear"), [])
                self.assertEqual(self._calls(gateway, "set"), [])

    def test_an_attempt_in_the_slot_the_synced_code_tracks_is_settled_without_a_readback(self):
        code = self._code(source=DoorCode.Source.SYNCED, slots={self.BACK: 1})
        self._attempt(code, 1)
        gateway = self._gateway({1: self.PIN}, cache={1: self.PIN})

        self._push_pending(gateway)

        self.assertEqual(self._unsettled_slots(code), [])
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(
            DoorCodeEvent.objects.get(door_code=code, metadata__action="unconfirmed_resolved").metadata["outcome"],
            "tracked",
        )


class SlotEmptyMarkerTests(_TrackingTestBase):
    """Issue #194: masked-slot trust once a slot has been seen empty."""

    def test_retention_keeps_a_slot_empty_marker_while_an_unsettled_attempt_on_that_slot_exists(self):
        code = self._code()
        self._attempt(code, 2, slot_available=True)
        lock_push_uc._settle_unconfirmed_slot(
            door_code=code, lock_entity_id=self.BACK, slot_index=2, outcome="not_holding_pin", slot_empty=True
        )
        marker = DoorCodeEvent.objects.get(door_code=code, metadata__action="unconfirmed_resolved")
        # The slot was seen empty, so a new pick of it isn't tagged.
        self.assertNotIn("slot_available", self._attempt(code, 2, slot_available=True).metadata)

        self._run_retention(DoorCodeEvent.objects.filter(door_code=code))

        self.assertTrue(DoorCodeEvent.objects.filter(id=marker.id).exists())
        self.assertNotIn("slot_available", self._attempt(code, 2, slot_available=True).metadata)

    def test_lock_sync_reads_an_untracked_attempt_slot_the_cache_calls_available_back_live(self):
        for name, script, settled, seen_empty in (
            ("empty", [EMPTY, EMPTY], True, True),
            ("empty once, then no answer", [EMPTY, *_timeouts(2)], False, True),
            # The set landed but the cache never heard about it: the live read shows the PIN.
            ("holds the pin", [_holding("4321")], False, False),
        ):
            with self.subTest(readback=name):
                DoorCodeEvent.objects.all().delete()
                DoorCode.objects.all().delete()
                code = self._code(push_state=DoorCode.PushState.PENDING)
                self._attempt(code, 3, slot_available=True)
                gateway = self._gateway({3: self.PIN})
                gateway._get_scripts = {None: list(script)}

                self._sync(gateway)

                self.assertEqual([c[1] for c in self._calls(gateway, "get")], [[3]] * len(script))
                self.assertEqual(self._calls(gateway, "clear"), [])
                self.assertEqual(self._unsettled_slots(code), [] if settled else [3])
                available = lock_push_uc._available_attempt_slots(door_code=code, lock_entity_id=self.BACK)
                self.assertEqual(available, set() if seen_empty or settled else {3})
                markers = lock_push_uc._slot_empty_markers(lock_entity_id=self.BACK, slot_index=3)
                self.assertEqual(bool(markers), seen_empty)

    def test_a_tracked_slot_seen_empty_once_is_no_longer_trusted_when_it_reads_back_masked(self):
        code = self._code(is_active=False, slots={self.BACK: 1})
        gateway = self._gateway({1: self.PIN})
        gateway._get_scripts = {None: [EMPTY, *_timeouts(2)]}

        lock_push_uc.clear_inactive_code_slots(door_code=code, zwavejs=gateway)

        # No verdict, so nothing is cleared, but the slot is only an untagged attempt now.
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._slots(code), {self.BACK: None})
        self.assertEqual(self._unsettled_slots(code), [1])
        self.assertEqual(lock_push_uc._available_attempt_slots(door_code=code, lock_entity_id=self.BACK), set())
        self.assertEqual(lock_push_uc.inactive_slots_to_clear(door_code=code), [(self.BACK, 1)])

        # A masked code there now may be a keypad code typed in since, so it's left alone.
        gateway._get_scripts = {None: [MASKED]}
        lock_push_uc.clear_inactive_code_slots(door_code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._unsettled_slots(code), [])
        self.assertEqual(lock_push_uc.inactive_slots_to_clear(door_code=code), [])

    def test_a_tracked_slot_seen_empty_once_is_still_cleared_when_it_shows_the_pin(self):
        code = self._code(is_active=False, slots={self.BACK: 1})
        gateway = self._gateway({1: self.PIN})
        gateway._get_scripts = {None: [EMPTY, *_timeouts(2)]}

        lock_push_uc.clear_inactive_code_slots(door_code=code, zwavejs=gateway)
        lock_push_uc.clear_inactive_code_slots(door_code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [1])])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(lock_push_uc.inactive_slots_to_clear(door_code=code), [])


class DuplicatePinTurnOnTests(_TrackingTestBase, APITestCase):
    """Issue #188: turning a code on whose PIN another code already has on its lock."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def _retired_code_and_keypad_copy(self) -> tuple[DoorCode, DoorCode, ClearFailingGateway]:
        retired = self._code(is_active=False, label="Dog walker")
        # Typed back in at the keypad after it was retired, and imported by lock sync.
        copy = self._code(source=DoorCode.Source.SYNCED, slots={self.BACK: 3}, label="Slot 3")
        return retired, copy, self._gateway({3: self.PIN}, cache={3: self.PIN})

    def test_turning_it_on_is_refused_with_a_409_naming_the_other_code(self):
        retired, copy, gateway = self._retired_code_and_keypad_copy()

        with self.assertRaises(door_codes_uc.DuplicatePinOnLock) as ctx:
            self._update(retired, gateway, {"is_active": True})
        message = str(ctx.exception)
        self.assertIn(f'{self.BACK} already has this PIN in slot 3 as door code {copy.id} ("Slot 3")', message)
        self.assertNotIn(self.PIN, message)
        retired.refresh_from_db()
        self.assertFalse(retired.is_active)
        self.assertEqual(gateway.invoke_calls, [])

        url = reverse("door-code-detail", args=[retired.id])
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.patch(url, {"is_active": True, "reauth_password": "pass"}, format="json")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(gateway.invoke_calls, [])

    def test_a_new_pin_in_the_same_save_or_another_lock_is_not_refused(self):
        retired, _copy, gateway = self._retired_code_and_keypad_copy()

        code = self._update(retired, gateway, {"is_active": True, "lock_entity_ids": [self.SIDE]})
        self.assertTrue(code.is_active)
        code = self._update(code, gateway, {"is_active": False})
        code = self._update(code, gateway, {"is_active": True, "code": "5555", "lock_entity_ids": [self.BACK]})
        self.assertTrue(code.is_active)

    def test_a_retired_code_with_the_same_pin_does_not_block(self):
        retired, copy, gateway = self._retired_code_and_keypad_copy()
        DoorCodeLockAssignment.objects.filter(door_code=copy).update(slot_index=None)
        DoorCode.objects.filter(id=copy.id).update(is_active=False)

        self.assertTrue(self._update(retired, gateway, {"is_active": True}).is_active)


class RetireSyncedCopiesTests(_TrackingTestBase):
    """Issue #185: a synced copy of an expiring code's PIN comes off its lock with it."""

    def test_retiring_a_code_clears_synced_copies_of_its_pin_on_its_locks(self):
        original, gateway = self._temporary_code([self.BACK])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        copy = self._code(source=DoorCode.Source.SYNCED, slots={self.BACK: 2}, label="Slot 2")
        other_pin = self._code(pin="9999", source=DoorCode.Source.SYNCED, slots={self.BACK: 3}, label="Slot 3")
        manual_copy = self._code(slots={self.BACK: 4})
        dated_copy = self._code(source=DoorCode.Source.SYNCED, slots={self.BACK: 5}, end_at=self._from_now(days=3))
        for slot, pin in ((2, self.PIN), (3, "9999"), (4, self.PIN), (5, self.PIN)):
            gateway._lock_codes[(12, slot)] = pin
        gateway.invoke_calls.clear()

        self._move(original, end_at=self._ago(minutes=1))
        self._enforce(gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {3: "9999", 4: self.PIN, 5: self.PIN})
        copy.refresh_from_db()
        self.assertFalse(copy.is_active)
        self.assertEqual(self._slots(copy), {self.BACK: None})
        event = self._updated_event(copy)
        self.assertEqual(event.metadata["reason"], "duplicate_of_retired_code")
        self.assertEqual(event.metadata["duplicate_of_door_code_id"], original.id)
        for untouched in (other_pin, manual_copy, dated_copy):
            untouched.refresh_from_db()
            self.assertTrue(untouched.is_active)


class WithdrawCapLeftoverTests(_TrackingTestBase):
    """The #207 review's leftovers: a code the withdraw capped, once it starts, and its audit event."""

    def _scheduled_pushed_code(self) -> tuple[DoorCode, ClearFailingGateway]:
        code, gateway = self._temporary_code([self.BACK])
        code = self._move(code, start_at=self._from_now(hours=1))
        # The withdraw's readback of the tracked slot never gets an answer.
        gateway._get_scripts = {None: _timeouts(30)}
        return code, gateway

    @staticmethod
    def _gave_up_events(code: DoorCode):
        return DoorCodeEvent.objects.filter(door_code=code, metadata__reason="max_attempts_exceeded")

    def test_a_code_the_withdraw_capped_is_refreshed_once_it_starts(self):
        code, gateway = self._scheduled_pushed_code()
        with patch("locks.tasks._get_push_max_attempts", return_value=1):
            self._enforce(gateway)
            code.refresh_from_db()
            self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
            self.assertIn("may still hold the PIN", code.last_push_error)

            self._move(code, start_at=timezone.now())
            self._enforce(gateway)

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")
        self.assertEqual(code.push_attempt_count, 0)
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})

    def test_a_withdraw_that_reaches_the_cap_writes_one_event(self):
        code, gateway = self._scheduled_pushed_code()
        with patch("locks.tasks._get_push_max_attempts", return_value=2):
            self._enforce(gateway)
            self.assertFalse(self._gave_up_events(code).exists())
            self._enforce(gateway)
            self._enforce(gateway)

        event = self._gave_up_events(code).get()
        self.assertEqual(event.event_type, DoorCodeEvent.EventType.CODE_FAILED)
        self.assertEqual(event.metadata["action"], "withdraw")
        self.assertEqual(event.metadata["attempts"], 2)
        self.assertNotIn(self.PIN, event.metadata["last_error"])
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
