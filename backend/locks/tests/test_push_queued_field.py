"""Issue #205: each ``lock_slot_assignments`` entry says whether the queued push task would still push that lock.

``push_queued`` has to agree with what ``push_requested_door_codes`` picks
(``queued_push_assignments`` plus ``locks_to_push``), including the parts the
browser can't see: the 10 minute TTL, the attempt cap and the schedule
re-queue's 1µs.
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from integrations_zwavejs.manager import ZwavejsCommandError
from rest_framework.test import APITestCase

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.tests.settings_test_utils import EncryptionTestMixin
from locks.models import DoorCode, DoorCodeLockAssignment
from locks.serializers import DoorCodePushSerializer, DoorCodeSerializer
from locks.use_cases import lock_push as lock_push_uc

BACK = "lock.back_door"
FRONT = "lock.front_door"
PIN = "4321"
MAX_ATTEMPTS = 3

PENDING = DoorCode.PushState.PENDING
PUSHED = DoorCode.PushState.PUSHED
FAILED = DoorCode.PushState.FAILED

_MAX_ATTEMPTS_PATH = "locks.tasks._get_push_max_attempts"


class PushQueuedFieldTests(EncryptionTestMixin, APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.owner = User.objects.create_user(email="owner@example.com", password="pass")
        self.now = timezone.now()
        patcher = patch(_MAX_ATTEMPTS_PATH, return_value=MAX_ATTEMPTS)
        self.max_attempts = patcher.start()
        self.addCleanup(patcher.stop)

    def _code(self, lock_entity_ids=(BACK,), **fields) -> DoorCode:
        code = DoorCode.objects.create(
            user=self.owner,
            encrypted_pin=SettingsEncryption.get().encrypt(PIN),
            pin_length=len(PIN),
            code_type=fields.pop("code_type", DoorCode.CodeType.PERMANENT),
            is_active=fields.pop("is_active", True),
            **fields,
        )
        for lock_entity_id in lock_entity_ids:
            DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=lock_entity_id)
        return code

    def _set(self, code: DoorCode, lock_entity_id: str = BACK, **fields) -> None:
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=lock_entity_id).update(**fields)

    def _queued(self, code: DoorCode, lock_entity_id: str = BACK, **fields) -> DoorCode:
        """``code`` with a push of ``lock_entity_id`` requested a second before ``self.now``."""
        self._set(code, lock_entity_id, push_requested_at=self.now - timedelta(seconds=1), **fields)
        return code

    def _fresh(self, code: DoorCode) -> DoorCode:
        return DoorCode.objects.select_related("user").prefetch_related("lock_assignments").get(id=code.id)

    def _entries(self, code: DoorCode, serializer=DoorCodeSerializer) -> dict[str, dict]:
        data = serializer(self._fresh(code), context={"now": self.now}).data
        return {entry["lock_entity_id"]: entry for entry in data["lock_slot_assignments"]}

    def _push_queued(self, code: DoorCode, lock_entity_id: str = BACK) -> bool:
        return self._entries(code)[lock_entity_id]["push_queued"]

    def _clear_failed(self, code: DoorCode, *, slot_index: int, removing: bool = False) -> None:
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=BACK,
            slot_index=slot_index,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin=PIN,
            removing=removing,
        )

    def _task_picks(self, code: DoorCode) -> set[str]:
        """The locks of ``code`` the queued push task would push at ``self.now``."""
        queued = lock_push_uc.queued_push_assignments(now=self.now, max_attempts=MAX_ATTEMPTS)
        return {
            a.lock_entity_id
            for a in lock_push_uc.locks_to_push(
                door_code=code, assignments=list(queued.filter(door_code=code).order_by("lock_entity_id"))
            )
        }

    def test_queued_until_a_push_attempt_comes_after_the_request(self):
        requested = self.now - timedelta(seconds=30)
        for name, attempt, expected in (
            ("never tried", None, True),
            ("tried before the request", requested - timedelta(seconds=5), True),
            ("tried at the request", requested, False),
            ("tried after the request", requested + timedelta(seconds=1), False),
        ):
            with self.subTest(name):
                code = self._code()
                self._set(code, push_requested_at=requested, last_push_attempt_at=attempt)
                self.assertIs(self._push_queued(code), expected)

    def test_the_schedule_requeue_one_microsecond_after_the_attempt_is_queued(self):
        # The budget ran out on the schedule right after the set, so the request
        # is stamped 1µs after the attempt (PR #201). Date.parse in the browser
        # keeps milliseconds only and read these as the same instant.
        # A fixed microsecond, so neither stamp drops its fraction or rolls the millisecond.
        attempt = self.now.replace(microsecond=123456) - timedelta(seconds=3)
        code = self._code()
        self._set(
            code,
            slot_index=2,
            schedule_pending=True,
            last_push_attempt_at=attempt,
            push_requested_at=attempt + timedelta(microseconds=1),
        )

        entry = self._entries(code)[BACK]
        self.assertTrue(entry["push_queued"])
        self.assertEqual(self._task_picks(code), {BACK})
        # The two timestamps the browser gets differ only below the millisecond.
        self.assertNotEqual(entry["push_requested_at"], entry["last_push_attempt_at"])
        self.assertEqual(entry["push_requested_at"][:23], entry["last_push_attempt_at"][:23])

    def test_a_request_lapses_after_the_ttl(self):
        ttl = lock_push_uc.PUSH_REQUEST_TTL
        for name, age, expected in (
            ("just inside", ttl - timedelta(microseconds=1), True),
            ("at the TTL", ttl, False),
            ("past it", ttl + timedelta(minutes=1), False),
        ):
            with self.subTest(name):
                code = self._code()
                self._set(code, push_requested_at=self.now - age)
                self.assertIs(self._push_queued(code), expected)
                self.assertEqual(self._task_picks(code), {BACK} if expected else set())

    def test_not_queued_without_a_request(self):
        self.assertFalse(self._push_queued(self._code()))

    def test_only_a_pending_lock_that_still_needs_a_push(self):
        for name, fields, expected in (
            ("pending, no slot", {}, True),
            ("pending, schedule pending", {"slot_index": 2, "schedule_pending": True}, True),
            ("pushed", {"slot_index": 2, "push_state": PUSHED}, False),
            ("failed", {"push_state": FAILED}, False),
            ("failed, schedule pending", {"slot_index": 2, "schedule_pending": True, "push_state": FAILED}, False),
            ("pending with a slot and nothing left to send", {"slot_index": 2}, False),
        ):
            with self.subTest(name):
                DoorCode.objects.all().delete()  # a slot is unique per lock
                code = self._queued(self._code(), **fields)
                self.assertIs(self._push_queued(code), expected)

    def test_not_queued_once_the_lock_hit_the_cap(self):
        for count, expected in ((MAX_ATTEMPTS - 1, True), (MAX_ATTEMPTS, False), (MAX_ATTEMPTS + 2, False)):
            with self.subTest(count=count):
                code = self._queued(self._code(), push_attempt_count=count)
                self.assertIs(self._push_queued(code), expected)

    def test_no_cap_when_it_is_turned_off(self):
        self.max_attempts.return_value = 0
        code = self._queued(self._code(), push_attempt_count=50)

        self.assertTrue(self._push_queued(code))

    def test_not_queued_on_a_code_thats_off_not_started_or_expired(self):
        temporary = DoorCode.CodeType.TEMPORARY
        for name, fields in (
            ("inactive", {"is_active": False}),
            ("not started", {"code_type": temporary, "start_at": self.now + timedelta(minutes=1)}),
            ("expired", {"code_type": temporary, "end_at": self.now - timedelta(minutes=1)}),
            ("ends right now", {"code_type": temporary, "end_at": self.now}),
        ):
            with self.subTest(name):
                code = self._queued(self._code(**fields))
                self.assertFalse(self._push_queued(code))

        started = self._queued(self._code(code_type=temporary, start_at=self.now, end_at=self.now + timedelta(hours=1)))
        self.assertTrue(self._push_queued(started))

    def test_not_queued_while_the_lock_is_being_dropped(self):
        code = self._queued(self._code([BACK, FRONT]))
        self._queued(code, FRONT)
        self._clear_failed(code, slot_index=2, removing=True)

        entries = self._entries(code)
        self.assertTrue(entries[BACK]["pending_removal"])
        self.assertFalse(entries[BACK]["push_queued"])
        self.assertTrue(entries[FRONT]["push_queued"])

    def test_not_queued_on_a_slot_whose_clear_is_outstanding(self):
        code = self._queued(self._code(), slot_index=2, schedule_pending=True)
        self._clear_failed(code, slot_index=2)

        self.assertFalse(self._push_queued(code))

    def test_still_queued_when_the_clear_is_for_another_slot_on_that_lock(self):
        # The PIN moved off slot 4, whose clear failed, and the lock still needs its set.
        code = self._queued(self._code())
        self._clear_failed(code, slot_index=4)

        self.assertTrue(self._push_queued(code))

    def test_agrees_with_what_the_task_picks(self):
        requested = self.now - timedelta(seconds=10)
        rows = {
            "fresh": {},
            "older attempt": {"last_push_attempt_at": requested - timedelta(seconds=1)},
            "same attempt": {"last_push_attempt_at": requested},
            "requeued 1µs": {
                "slot_index": 2,
                "schedule_pending": True,
                "last_push_attempt_at": requested - timedelta(microseconds=1),
            },
            "lapsed": {"push_requested_at": self.now - lock_push_uc.PUSH_REQUEST_TTL},
            "capped": {"push_attempt_count": MAX_ATTEMPTS},
            "pushed": {"slot_index": 2, "push_state": PUSHED},
            "failed": {"push_state": FAILED},
            "no request": {"push_requested_at": None},
        }
        for name, fields in rows.items():
            with self.subTest(name):
                DoorCode.objects.all().delete()  # a slot is unique per lock
                code = self._code([BACK, FRONT])
                self._set(code, push_requested_at=requested)
                self._set(code, FRONT, **{"push_requested_at": requested, **fields})
                entries = self._entries(code)
                picked = self._task_picks(code)
                self.assertEqual({k for k, entry in entries.items() if entry["push_queued"]}, picked)
                self.assertIn(BACK, picked)

    def test_reads_the_cap_once_for_a_whole_list_and_not_at_all_with_nothing_queued(self):
        codes = [self._queued(self._code()) for _ in range(3)]
        fresh = (
            DoorCode.objects.select_related("user")
            .prefetch_related("lock_assignments")
            .filter(id__in=[c.id for c in codes])
        )

        data = DoorCodeSerializer(fresh, many=True, context={"now": self.now}).data

        self.assertTrue(all(code["lock_slot_assignments"][0]["push_queued"] for code in data))
        self.assertEqual(self.max_attempts.call_count, 1)

        self.max_attempts.reset_mock()
        idle = self._fresh(self._code())
        idle_data = DoorCodeSerializer([idle], many=True, context={"now": self.now}).data

        self.assertFalse(idle_data[0]["lock_slot_assignments"][0]["push_queued"])
        self.max_attempts.assert_not_called()

    def test_the_list_and_retry_responses_have_it_and_no_pin(self):
        code = self._queued(self._code())
        self.client.force_authenticate(self.admin)

        response = self.client.get(reverse("door-codes"), {"user_id": str(self.owner.id)})

        self.assertEqual(response.status_code, 200, response.content)
        [listed] = response.json()["data"]
        retry_payload = DoorCodePushSerializer(self._fresh(code), context={"now": self.now}).data

        # Ids and timestamps are left out of the check since their digits can happen to match.
        noisy = {"id", "user_id", "created_at", "updated_at", "last_push_attempt_at", "push_requested_at"}

        def without_noise(entry: dict) -> dict:
            return {k: v for k, v in entry.items() if k not in noisy}

        for payload in (listed, retry_payload):
            [entry] = payload["lock_slot_assignments"]
            self.assertIs(entry["push_queued"], True)
            self.assertNotIn(PIN, json.dumps(without_noise(entry)))
            self.assertNotIn("encrypted_pin", json.dumps(entry))
        # The retry response has no PIN at all.
        retry_rest = without_noise({**retry_payload, "lock_slot_assignments": None, "lock_assignments": None})
        self.assertNotIn(PIN, json.dumps(retry_rest, default=str))
        self.assertNotIn("pin", retry_payload)
