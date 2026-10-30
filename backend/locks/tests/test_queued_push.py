"""Issue #124: create, update and Retry queue the door code push for the scheduler instead of making it in the request.

"The push task is running" is patched in at ``scheduler.runner.is_task_running``,
which is what ``lock_push.push_task_running`` asks, and ``wake_task`` is a mock
so the tests can count wakes. Without the patch no scheduler runs in tests, so
the saves push inline like before.
"""

from __future__ import annotations

import contextlib
from datetime import timedelta
from unittest.mock import patch

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from integrations_zwavejs.manager import ZwavejsCommandError
from rest_framework.test import APITestCase

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.models import Entity
from alarm.tests.settings_test_utils import EncryptionTestMixin
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.tests.test_door_code_locking import _free_elsewhere, _OtherHolder, _when_waiting_on
from locks.tests.test_lock_push import FakeGateway
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_config_sync as lock_config_sync_uc
from locks.use_cases import lock_push as lock_push_uc

BACK = "lock.back_door"  # node 12
SIDE = "lock.side_door"  # node 13
FRONT = "lock.front_door"  # node 14
PIN = "4321"
TASK = "push_requested_door_codes"

PENDING = DoorCode.PushState.PENDING
PUSHED = DoorCode.PushState.PUSHED
FAILED = DoorCode.PushState.FAILED


@contextlib.contextmanager
def push_task_running():
    """The push task runs in this process; yields the ``wake_task`` mock."""
    with (
        patch("scheduler.runner.is_task_running", return_value=True),
        patch("scheduler.runner.wake_task", return_value=True) as wake,
    ):
        yield wake


class _FakeClock:
    """Stands in for ``lock_push._time``, so a budget runs out without real waiting."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class SlowGateway(FakeGateway):
    """A FakeGateway whose calls to ``slow_nodes`` each take ``step`` seconds on ``clock``."""

    def __init__(self, *, clock: _FakeClock, slow_nodes: set[int], step: float, **kwargs):
        super().__init__(**kwargs)
        self.clock = clock
        self.slow_nodes = slow_nodes
        self.step = step

    def _tick(self, node_id: int) -> None:
        if node_id in self.slow_nodes:
            self.clock.now += self.step

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0):
        self._tick(node_id)
        return super().node_get_defined_value_ids(node_id=node_id, timeout_seconds=timeout_seconds)

    def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0):
        self._tick(node_id)
        return super().node_get_value(node_id=node_id, value_id=value_id, timeout_seconds=timeout_seconds)

    def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
        self._tick(node_id)
        return super().invoke_cc_api(
            node_id=node_id,
            command_class=command_class,
            method_name=method_name,
            args=args,
            timeout_seconds=timeout_seconds,
        )


class _SetHookGateway(FakeGateway):
    """Runs ``on_set(node_id)`` before each CC 99 ``set``."""

    on_set = None

    def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
        if command_class == 99 and method_name == "set" and self.on_set is not None:
            self.on_set(node_id)
        return super().invoke_cc_api(
            node_id=node_id,
            command_class=command_class,
            method_name=method_name,
            args=args,
            timeout_seconds=timeout_seconds,
        )


class _QueuedPushTestBase(EncryptionTestMixin, TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.owner = User.objects.create_user(email="owner@example.com", password="pass")
        for entity_id, name, node_id in ((BACK, "Back Door", 12), (SIDE, "Side Door", 13), (FRONT, "Front Door", 14)):
            Entity.objects.create(
                entity_id=entity_id,
                domain="lock",
                name=name,
                attributes={"zwavejs": {"node_id": node_id}},
                source="home_assistant",
            )
        self.gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True)
        for patcher in (
            patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0)),
            patch.object(lock_config_sync_uc, "_SYNC_LOCK_POLL_SECONDS", (0.01, 0.01)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _code(self, lock_entity_ids: list[str], *, pin: str = PIN, **fields) -> DoorCode:
        """An active code on the locks with no slot yet."""
        code = DoorCode.objects.create(
            user=self.owner,
            encrypted_pin=SettingsEncryption.get().encrypt(pin),
            pin_length=len(pin),
            code_type=fields.pop("code_type", DoorCode.CodeType.PERMANENT),
            is_active=fields.pop("is_active", True),
            **fields,
        )
        for entity_id in lock_entity_ids:
            DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=entity_id)
        return code

    def _queue(self, code: DoorCode, *, at=None, by: User | None = None, **assignment_fields) -> None:
        DoorCodeLockAssignment.objects.filter(door_code=code).update(
            push_requested_at=at or timezone.now(), push_requested_by=by or self.admin, **assignment_fields
        )

    def _run_task(self, gateway: FakeGateway | None = None) -> int:
        from locks.tasks import push_requested_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway or self.gateway):
            return push_requested_door_codes()

    def _fresh(self, code: DoorCode) -> DoorCode:
        return DoorCode.objects.select_related("user").prefetch_related("lock_assignments").get(id=code.id)

    def _assignment(self, code: DoorCode, lock_entity_id: str) -> DoorCodeLockAssignment:
        return DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=lock_entity_id)

    def _slots(self, code: DoorCode) -> dict[str, int | None]:
        return dict(DoorCodeLockAssignment.objects.filter(door_code=code).values_list("lock_entity_id", "slot_index"))

    def _calls(self, gateway: FakeGateway, method_name: str) -> list[tuple[int, list]]:
        return [
            (c["node_id"], c["args"])
            for c in gateway.invoke_calls
            if c["command_class"] == 99 and c["method_name"] == method_name
        ]

    def _assert_no_lock_traffic(self, gateway: FakeGateway | None = None) -> None:
        gateway = gateway or self.gateway
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(gateway.value_id_fetches, 0)


class RequestPushTests(_QueuedPushTestBase):
    def test_stamps_the_locks_that_need_a_push_and_wakes_the_task_once_on_commit(self):
        code = self._code([BACK, SIDE, FRONT])
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=SIDE).update(
            slot_index=1, push_state=PUSHED
        )
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=FRONT).update(push_state=FAILED)

        with push_task_running() as wake, self.captureOnCommitCallbacks(execute=True):
            stamped = lock_push_uc.request_push(code, actor_user=self.admin)
            wake.assert_not_called()

        self.assertEqual(stamped, [BACK])
        wake.assert_called_once_with(TASK)
        back = self._assignment(code, BACK)
        self.assertIsNotNone(back.push_requested_at)
        self.assertEqual(back.push_requested_by, self.admin)
        for lock_entity_id in (SIDE, FRONT):
            self.assertIsNone(self._assignment(code, lock_entity_id).push_requested_at, lock_entity_id)

    def test_a_rollback_neither_stamps_nor_wakes(self):
        code = self._code([BACK])

        with (
            push_task_running() as wake,
            self.captureOnCommitCallbacks(execute=True) as callbacks,
            self.assertRaises(RuntimeError),
            transaction.atomic(),
        ):
            lock_push_uc.request_push(code, actor_user=self.admin)
            raise RuntimeError("the save failed")

        wake.assert_not_called()
        self.assertEqual(callbacks, [])
        self.assertIsNone(self._assignment(code, BACK).push_requested_at)

    def test_limited_to_the_locks_given(self):
        code = self._code([BACK, SIDE])

        with push_task_running(), self.captureOnCommitCallbacks(execute=True):
            stamped = lock_push_uc.request_push(code, [SIDE], actor_user=self.admin)

        self.assertEqual(stamped, [SIDE])
        self.assertIsNone(self._assignment(code, BACK).push_requested_at)

    def test_nothing_for_a_code_nothing_would_push(self):
        now = timezone.now()
        codes = {
            "inactive": self._code([BACK], is_active=False),
            "not started": self._code([BACK], code_type=DoorCode.CodeType.TEMPORARY, start_at=now + timedelta(hours=1)),
            "expired": self._code([BACK], code_type=DoorCode.CodeType.TEMPORARY, end_at=now - timedelta(minutes=1)),
        }

        with push_task_running() as wake, self.captureOnCommitCallbacks(execute=True):
            for name, code in codes.items():
                with self.subTest(name):
                    self.assertEqual(lock_push_uc.request_push(code, actor_user=self.admin), [])

        wake.assert_not_called()
        self.assertFalse(DoorCodeLockAssignment.objects.filter(push_requested_at__isnull=False).exists())


class DeferredSaveApiTests(_QueuedPushTestBase, APITestCase):
    """With the push task running, the request saves, stamps and returns pending without talking to the lock."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin)

    def _request(self, method: str, url: str, data: dict | None = None):
        with (
            push_task_running() as wake,
            patch("locks.views.door_codes.default_zwavejs_gateway", self.gateway),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = getattr(self.client, method)(url, data or {}, format="json")
        return response, wake

    def _pushed_inline(self, lock_entity_ids: list[str]) -> DoorCode:
        code = door_codes_uc.create_door_code(
            user=self.owner, raw_code=PIN, lock_entity_ids=lock_entity_ids, actor_user=self.admin, zwavejs=self.gateway
        )
        self.gateway.invoke_calls.clear()
        self.gateway.value_id_fetches = 0
        return code

    def test_create_returns_pending_and_makes_no_gateway_call(self):
        response, wake = self._request(
            "post",
            reverse("door-codes"),
            {
                "user_id": str(self.owner.id),
                "code": PIN,
                "code_type": DoorCode.CodeType.PERMANENT,
                "lock_entity_ids": [BACK, SIDE],
                "reauth_password": "pass",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertEqual(data["push_state"], PENDING)
        self._assert_no_lock_traffic()
        wake.assert_called_once_with(TASK)
        code = DoorCode.objects.get(id=data["id"])
        for lock_entity_id in (BACK, SIDE):
            assignment = self._assignment(code, lock_entity_id)
            self.assertIsNotNone(assignment.push_requested_at)
            self.assertEqual(assignment.push_requested_by, self.admin)
            self.assertIsNone(assignment.slot_index)
        self.assertTrue(all(entry["push_requested_at"] for entry in data["lock_slot_assignments"]))

    def test_adding_a_lock_returns_pending_and_makes_no_gateway_call(self):
        code = self._pushed_inline([BACK])

        response, wake = self._request(
            "patch",
            reverse("door-code-detail", args=[code.id]),
            {"lock_entity_ids": [BACK, SIDE], "reauth_password": "pass"},
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["push_state"], PENDING)
        self._assert_no_lock_traffic()
        wake.assert_called_once_with(TASK)
        self.assertIsNotNone(self._assignment(code, SIDE).push_requested_at)
        self.assertEqual(self._assignment(code, SIDE).push_requested_by, self.admin)
        # BACK keeps its slot and needs nothing.
        self.assertIsNone(self._assignment(code, BACK).push_requested_at)

    def test_a_pin_change_clears_in_the_request_and_queues_the_push(self):
        code = self._pushed_inline([BACK, SIDE])

        response, wake = self._request(
            "patch",
            reverse("door-code-detail", args=[code.id]),
            {"code": "5555", "reauth_password": "pass"},
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["push_state"], PENDING)
        # Only the clears of the old slots: no set, no readback, no slot search.
        self.assertEqual(sorted(c["method_name"] for c in self.gateway.invoke_calls), ["clear", "clear"])
        self.assertEqual(self.gateway.value_id_fetches, 0)
        wake.assert_called_once_with(TASK)
        self.assertEqual(self._slots(code), {BACK: None, SIDE: None})
        for lock_entity_id in (BACK, SIDE):
            self.assertIsNotNone(self._assignment(code, lock_entity_id).push_requested_at)

        self.gateway.invoke_calls.clear()
        self.assertEqual(self._run_task(), 2)
        self.assertEqual(sorted(self._calls(self.gateway, "set")), [(12, [1, 1, "5555"]), (13, [1, 1, "5555"])])
        code.refresh_from_db()
        self.assertEqual(code.push_state, PUSHED)

    def test_retry_returns_pending_and_makes_no_gateway_call(self):
        code = self._code([BACK])
        DoorCodeLockAssignment.objects.filter(door_code=code).update(
            push_state=FAILED, push_attempt_count=3, last_push_error="Lock rejected the code"
        )
        lock_push_uc.refresh_push_state(door_code=code)
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, FAILED)

        response, wake = self._request("post", reverse("door-code-push", args=[code.id]))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["push_state"], PENDING)
        self._assert_no_lock_traffic()
        wake.assert_called_once_with(TASK)
        back = self._assignment(code, BACK)
        self.assertEqual((back.push_state, back.push_attempt_count), (PENDING, 0))
        self.assertIsNotNone(back.push_requested_at)
        self.assertEqual(back.push_requested_by, self.admin)

        self._run_task()
        self.assertEqual(self._calls(self.gateway, "set"), [(12, [1, 1, PIN])])
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, PUSHED)


class InlineFallbackTests(_QueuedPushTestBase):
    """Without the push task in this process (SCHEDULER_ENABLED=False, no leader, tests), saves push inline."""

    def test_create_pushes_inline_without_queueing(self):
        with patch("scheduler.runner.wake_task") as wake:
            code = door_codes_uc.create_door_code(
                user=self.owner, raw_code=PIN, lock_entity_ids=[BACK], actor_user=self.admin, zwavejs=self.gateway
            )

        self.assertEqual(self._calls(self.gateway, "set"), [(12, [1, 1, PIN])])
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, PUSHED)
        self.assertIsNone(self._assignment(code, BACK).push_requested_at)
        wake.assert_not_called()

    def test_update_pushes_only_after_letting_go_of_its_locks(self):
        gateway = _SetHookGateway(usersNumber=5, cache_updates_on_set=True)
        code = door_codes_uc.create_door_code(
            user=self.owner, raw_code=PIN, lock_entity_ids=[BACK], actor_user=self.admin, zwavejs=gateway
        )
        back_free_during_set: list[bool] = []
        gateway.on_set = lambda node_id: back_free_during_set.append(_free_elsewhere(BACK))

        door_codes_uc.update_door_code(
            code=self._fresh(code), changes={"lock_entity_ids": [BACK, FRONT]}, actor_user=self.admin, zwavejs=gateway
        )

        # The update held BACK and FRONT; FRONT's push ran once it had let go of them.
        self.assertEqual(back_free_during_set, [True])
        self.assertEqual(self._slots(code), {BACK: 1, FRONT: 1})
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, PUSHED)

    def test_each_inline_lock_push_has_its_own_budget(self):
        clock = _FakeClock()
        gateway = SlowGateway(clock=clock, slow_nodes={12}, step=2.0, usersNumber=5, cache_updates_on_set=True)

        with (
            patch.object(lock_push_uc, "_time", clock),
            patch.object(lock_push_uc, "PUSH_LOCK_BUDGET_SECONDS", 1.0),
        ):
            code = door_codes_uc.create_door_code(
                user=self.owner, raw_code=PIN, lock_entity_ids=[BACK, SIDE], actor_user=self.admin, zwavejs=gateway
            )

        # BACK ran out of time before its set and isn't counted; SIDE had its own budget.
        self.assertEqual(self._calls(gateway, "set"), [(13, [1, 1, PIN])])
        back = self._assignment(code, BACK)
        self.assertEqual((back.slot_index, back.push_state, back.push_attempt_count), (None, PENDING, 0))
        self.assertIn("TimeBudgetExceeded", back.last_push_error)
        self.assertEqual(self._assignment(code, SIDE).push_state, PUSHED)


class PushRequestedTaskTests(_QueuedPushTestBase):
    def test_pushes_the_queued_locks_with_the_requester_on_the_event(self):
        code = self._code([BACK, SIDE])
        self._queue(code)

        self.assertEqual(self._run_task(), 2)

        self.assertEqual(sorted(self._calls(self.gateway, "set")), [(12, [1, 1, PIN]), (13, [1, 1, PIN])])
        self.assertEqual(self._slots(code), {BACK: 1, SIDE: 1})
        code.refresh_from_db()
        self.assertEqual(code.push_state, PUSHED)
        events = DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        self.assertEqual(
            sorted(events.values_list("lock_entity_id", "user_id")), [(BACK, self.admin.id), (SIDE, self.admin.id)]
        )

    def test_a_requester_that_was_deleted_falls_back_to_the_code_owner(self):
        code = self._code([BACK])
        requester = User.objects.create_user(email="gone@example.com", password="pass")
        self._queue(code, by=requester)
        requester.delete()

        self._run_task()

        event = DoorCodeEvent.objects.get(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        self.assertEqual(event.user, self.owner)

    def test_a_second_run_does_nothing(self):
        code = self._code([BACK])
        self._queue(code)
        self._run_task()
        self.gateway.invoke_calls.clear()
        self.gateway.value_id_fetches = 0

        self.assertEqual(self._run_task(), 0)

        self._assert_no_lock_traffic()
        self.assertEqual(self._slots(code), {BACK: 1})

    def test_only_a_pending_schedule_is_sent_to_a_slot_that_holds_the_pin(self):
        code = self._code([BACK], days_of_week=0b0000001)
        self._queue(code, slot_index=3, schedule_pending=True)

        self._run_task()

        self.assertEqual(self._calls(self.gateway, "set"), [])
        schedules = [c for c in self.gateway.invoke_calls if c["command_class"] == 78]
        self.assertEqual(len(schedules), 1)
        back = self._assignment(code, BACK)
        self.assertEqual((back.slot_index, back.push_state, back.schedule_pending), (3, PUSHED, False))

    def test_skips_locks_nothing_should_be_sent_to(self):
        now = timezone.now()
        failed = self._code([BACK])
        self._queue(failed, push_state=FAILED)
        removing = self._code([BACK])
        self._queue(removing, slot_index=2, schedule_pending=True)
        lock_push_uc.record_clear_failure(
            door_code=removing,
            lock_entity_id=BACK,
            slot_index=2,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin=PIN,
            removing=True,
        )
        not_started = self._code([BACK], code_type=DoorCode.CodeType.TEMPORARY, start_at=now + timedelta(hours=1))
        self._queue(not_started)
        expired = self._code([BACK], code_type=DoorCode.CodeType.TEMPORARY, end_at=now - timedelta(minutes=1))
        self._queue(expired)
        inactive = self._code([BACK], is_active=False)
        self._queue(inactive)
        slotted = self._code([BACK])
        self._queue(slotted, slot_index=1, push_state=PUSHED)
        lapsed = self._code([BACK])
        self._queue(lapsed, at=now - lock_push_uc.PUSH_REQUEST_TTL - timedelta(seconds=1))
        attempted_since = self._code([BACK])
        self._queue(attempted_since, at=now - timedelta(minutes=1))
        DoorCodeLockAssignment.objects.filter(door_code=attempted_since).update(last_push_attempt_at=now)
        at_cap = self._code([BACK])
        self._queue(at_cap, push_attempt_count=24)

        self.assertFalse(lock_push_uc.queued_push_assignments(now=timezone.now(), max_attempts=24).exists())
        self.assertEqual(self._run_task(), 0)

        self._assert_no_lock_traffic()

    def test_an_idle_tick_is_one_query(self):
        self._code([BACK])

        with self.assertNumQueries(1):
            self.assertEqual(self._run_task(), 0)

    def test_a_busy_lock_is_waited_for_then_pushed(self):
        code = self._code([BACK])
        self._queue(code)
        holder = _OtherHolder(BACK).acquire()
        self.addCleanup(holder.release)

        with _when_waiting_on(BACK, holder.release) as waited:
            self._run_task()

        self.assertTrue(waited)
        self.assertEqual(self._calls(self.gateway, "set"), [(12, [1, 1, PIN])])
        self.assertEqual(self._slots(code), {BACK: 1})

    def test_a_lock_still_busy_at_the_wait_stays_queued_and_uncounted(self):
        code = self._code([BACK])
        self._queue(code)
        holder = _OtherHolder(BACK).acquire()
        self.addCleanup(holder.release)

        with patch("locks.tasks._QUEUED_PUSH_LOCK_WAIT_SECONDS", 0.05):
            self._run_task()

        self._assert_no_lock_traffic()
        back = self._assignment(code, BACK)
        self.assertEqual((back.push_state, back.push_attempt_count, back.last_push_attempt_at), (PENDING, 0, None))

        holder.release()
        self._run_task()
        self.assertEqual(self._slots(code), {BACK: 1})

    def test_out_of_budget_before_the_set_leaves_the_lock_pending_and_uncounted(self):
        clock = _FakeClock()
        gateway = SlowGateway(clock=clock, slow_nodes={12}, step=2.0, usersNumber=5, cache_updates_on_set=True)
        code = self._code([BACK, SIDE])
        self._queue(code)

        with patch.object(lock_push_uc, "_time", clock), patch.object(lock_push_uc, "PUSH_LOCK_BUDGET_SECONDS", 1.0):
            self._run_task(gateway)

        # Nothing went to BACK's slots, and SIDE had a budget of its own.
        self.assertEqual(self._calls(gateway, "set"), [(13, [1, 1, PIN])])
        back = self._assignment(code, BACK)
        self.assertEqual((back.slot_index, back.push_state, back.push_attempt_count), (None, PENDING, 0))
        self.assertIn("TimeBudgetExceeded", back.last_push_error)
        self.assertFalse(DoorCodeEvent.objects.filter(door_code=code, metadata__action="push_unconfirmed").exists())
        self.assertEqual(self._assignment(code, SIDE).push_state, PUSHED)
        code.refresh_from_db()
        self.assertEqual(code.push_state, PENDING)

        # The attempt used the request up, so it's the 300s retry's now, not every 5s.
        gateway.invoke_calls.clear()
        with patch.object(lock_push_uc, "_time", clock):
            self.assertEqual(self._run_task(gateway), 0)
        self.assertEqual(gateway.invoke_calls, [])

    def test_out_of_budget_after_the_set_keeps_the_slot_on_record_and_is_uncounted(self):
        clock = _FakeClock()
        gateway = SlowGateway(clock=clock, slow_nodes={12}, step=1.0, usersNumber=5, cache_updates_on_set=True)
        code = self._code([BACK])
        self._queue(code)

        # Value ids, slot count, slot 1's status and the set take 4s; the readback doesn't fit.
        with patch.object(lock_push_uc, "_time", clock), patch.object(lock_push_uc, "PUSH_LOCK_BUDGET_SECONDS", 3.5):
            self._run_task(gateway)

        self.assertEqual(self._calls(gateway, "set"), [(12, [1, 1, PIN])])
        self.assertEqual(self._calls(gateway, "get"), [])
        back = self._assignment(code, BACK)
        self.assertEqual((back.slot_index, back.push_state, back.push_attempt_count), (None, PENDING, 0))
        marker = DoorCodeEvent.objects.get(door_code=code, metadata__action="push_unconfirmed")
        self.assertEqual((marker.lock_entity_id, marker.metadata["slot_index"]), (BACK, 1))
        # So a delete still clears it, and the next push re-sends to it (issue #128).
        self.assertTrue(marker.metadata.get("slot_available"))

    def test_a_queued_attempt_counts_once_and_leaves_other_codes_counts_alone(self):
        gateway = FakeGateway(
            usersNumber=5,
            cache_updates_on_set=True,
            get_responses={12: [ZwavejsCommandError("timed out")] * 3},
        )
        code = self._code([BACK])
        self._queue(code)
        other = self._code([SIDE], pin="5555")
        DoorCodeLockAssignment.objects.filter(door_code=other).update(push_attempt_count=5)

        self._run_task(gateway)

        self.assertEqual(self._assignment(code, BACK).push_attempt_count, 1)
        self.assertEqual(self._assignment(other, SIDE).push_attempt_count, 5)

    def test_a_queued_attempt_counts_like_an_inline_one(self):
        def failing_gateway() -> FakeGateway:
            return FakeGateway(
                usersNumber=5, cache_updates_on_set=True, get_responses={12: [ZwavejsCommandError("timed out")] * 3}
            )

        inline = door_codes_uc.create_door_code(
            user=self.owner, raw_code=PIN, lock_entity_ids=[BACK], actor_user=self.admin, zwavejs=failing_gateway()
        )
        queued = self._code([BACK], pin="5555")
        self._queue(queued)
        self._run_task(failing_gateway())

        self.assertEqual(self._assignment(inline, BACK).push_attempt_count, 1)
        self.assertEqual(self._assignment(queued, BACK).push_attempt_count, 1)


class Migration0011Tests(TransactionTestCase):
    """Migration 0011 is additive: old rows read as nothing queued, and old code can still insert."""

    BEFORE = [("locks", "0010_backfill_assignment_push_state")]
    AFTER = [("locks", "0011_assignment_push_requested")]

    def setUp(self):
        super().setUp()
        # A push or lock sync in an earlier test leaves a rule dispatch reading the
        # DB in a background thread. On SQLite it can't run during a table rebuild,
        # so let it finish first. The pool is made again on the next dispatch.
        from alarm.dispatcher.dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        timer = dispatcher._debounce_timer
        if timer is not None:
            timer.join(timeout=5)
        pool, dispatcher._worker_pool = dispatcher._worker_pool, None
        if pool is not None:
            pool.shutdown(wait=True)

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_forward_keeps_rows_with_nothing_queued_and_back_again(self):
        old = self._migrate(self.BEFORE)
        user = old.get_model("accounts", "User").objects.create(email="u@example.com", password="x")
        code = old.get_model("locks", "DoorCode").objects.create(user_id=user.id, code_type="permanent")
        assignment = old.get_model("locks", "DoorCodeLockAssignment").objects.create(
            door_code_id=code.id, lock_entity_id=BACK, slot_index=2
        )

        new = self._migrate(self.AFTER)
        row = new.get_model("locks", "DoorCodeLockAssignment").objects.get(id=assignment.id)
        self.assertEqual((row.slot_index, row.push_requested_at, row.push_requested_by_id), (2, None, None))

        self._migrate(self.BEFORE)
        row = old.get_model("locks", "DoorCodeLockAssignment").objects.get(id=assignment.id)
        self.assertEqual(row.slot_index, 2)
        self._migrate(self.AFTER)

    def test_an_insert_without_the_new_columns_still_works(self):
        user = User.objects.create_user(email="u@example.com", password="pass")
        code = DoorCode.objects.create(user=user, code_type=DoorCode.CodeType.PERMANENT)
        now = connection.ops.adapt_datetimefield_value(timezone.now())
        qn = connection.ops.quote_name
        # The columns code from before 0011 writes (0009's included).
        columns = ("door_code_id", "lock_entity_id", "slot_index", "created_at", "updated_at")

        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {qn(DoorCodeLockAssignment._meta.db_table)} ({', '.join(qn(c) for c in columns)}) "
                "VALUES (%s, %s, %s, %s, %s)",
                [code.id, BACK, None, now, now],
            )

        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual((assignment.push_requested_at, assignment.push_requested_by_id), (None, None))

    def test_deleting_the_requester_keeps_the_assignment(self):
        user = User.objects.create_user(email="u@example.com", password="pass")
        requester = User.objects.create_user(email="r@example.com", password="pass")
        code = DoorCode.objects.create(user=user, code_type=DoorCode.CodeType.PERMANENT)
        DoorCodeLockAssignment.objects.create(
            door_code=code, lock_entity_id=BACK, push_requested_at=timezone.now(), push_requested_by=requester
        )

        requester.delete()

        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertIsNone(assignment.push_requested_by_id)
        self.assertIsNotNone(assignment.push_requested_at)
