"""Counting door code uses from keypad unlocks (issue #145, ADR-0114)."""

from __future__ import annotations

import threading
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from integrations_zwavejs.manager import ZwavejsCommandError

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.models import Entity
from alarm.tests.settings_test_utils import EncryptionTestMixin
from locks import runtime as locks_runtime
from locks.keypad_events import KeypadUnlock
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.code_usage import (
    DEDUPE_WINDOW,
    UseOutcome,
    handle_keypad_unlock,
    lock_entity_ids_for_node,
    record_keypad_use,
)

HOME_ID = 4170970308
BACK = "lock.back_door"  # node 12
SIDE = "lock.side_door"  # node 13
PIN = "4321"


def _lock_entity(entity_id: str, node_id: int, **zwavejs) -> Entity:
    return Entity.objects.create(
        entity_id=entity_id,
        domain="lock",
        name=entity_id,
        attributes={"zwavejs": {"node_id": node_id, **zwavejs}},
        source="home_assistant",
    )


class _UsageTestBase(EncryptionTestMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="guest@example.com", password="pass")
        _lock_entity(BACK, 12, home_id=HOME_ID)
        _lock_entity(SIDE, 13)  # no home id recorded
        # Entity sync makes one entity per value, so a node has more than its lock.
        Entity.objects.create(
            entity_id="zwavejs:4170970308:12:128:0:level",
            domain="sensor",
            name="Back Door battery",
            attributes={"zwavejs": {"node_id": 12, "home_id": HOME_ID}},
            source="zwavejs",
        )

    def _code(self, *, slots: dict[str, int] | None = None, **kwargs) -> DoorCode:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(PIN),
            pin_length=len(PIN),
            code_type=kwargs.pop("code_type", DoorCode.CodeType.PERMANENT),
            push_state=DoorCode.PushState.PUSHED,
            **kwargs,
        )
        for lock_entity_id, slot_index in (slots or {BACK: 3}).items():
            DoorCodeLockAssignment.objects.create(
                door_code=code,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                push_state=DoorCode.PushState.PUSHED,
            )
        return code

    def _unlock(self, *, node_id: int = 12, slot: int = 3, event: int = 6, now=None) -> UseOutcome:
        return handle_keypad_unlock(KeypadUnlock(node_id=node_id, slot=slot, event=event), home_id=HOME_ID, now=now)

    def _uses(self, *, lock_entity_id: str | None = None):
        events = DoorCodeEvent.objects.filter(event_type=DoorCodeEvent.EventType.CODE_USED).order_by("id")
        if lock_entity_id is not None:
            events = events.filter(lock_entity_id=lock_entity_id)
        return list(events)

    def _age_uses(self, seconds: float) -> None:
        DoorCodeEvent.objects.filter(event_type=DoorCodeEvent.EventType.CODE_USED).update(
            created_at=timezone.now() - timedelta(seconds=seconds)
        )


class CountingTests(_UsageTestBase):
    def test_a_keypad_unlock_counts_one_use_on_the_code_and_lock(self):
        code = self._code(max_uses=5)
        now = timezone.now()

        self.assertEqual(self._unlock(now=now), UseOutcome.COUNTED)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 1)
        self.assertEqual(code.last_used_at, now)
        self.assertEqual(code.last_used_lock, BACK)
        (event,) = self._uses()
        self.assertEqual(event.door_code_id, code.id)
        self.assertEqual(event.lock_entity_id, BACK)
        self.assertEqual(
            event.metadata,
            {
                "slot_index": 3,
                "source": "zwavejs",
                "notification_event": 6,
                "uses_count": 1,
                "max_uses": 5,
                "over_limit": False,
            },
        )

    def test_event_34_counts_like_event_6(self):
        code = self._code()
        self.assertEqual(self._unlock(event=34), UseOutcome.COUNTED)
        code.refresh_from_db()
        self.assertEqual(code.uses_count, 1)
        self.assertEqual(self._uses()[0].metadata["notification_event"], 34)

    def test_a_second_report_inside_the_window_is_the_same_use(self):
        code = self._code()
        self.assertEqual(self._unlock(event=6), UseOutcome.COUNTED)
        self._age_uses(DEDUPE_WINDOW.total_seconds() - 2)

        # The same unlock reported again, or as the newer event.
        self.assertEqual(self._unlock(event=6), UseOutcome.DUPLICATE)
        self.assertEqual(self._unlock(event=34), UseOutcome.DUPLICATE)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 1)
        self.assertEqual(len(self._uses()), 1)

    def test_a_use_outside_the_window_counts_again(self):
        code = self._code()
        self._unlock()
        self._age_uses(DEDUPE_WINDOW.total_seconds() + 1)

        self.assertEqual(self._unlock(), UseOutcome.COUNTED)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 2)
        self.assertEqual([e.metadata["uses_count"] for e in self._uses()], [1, 2])

    def test_uses_are_one_total_across_the_codes_locks(self):
        code = self._code(slots={BACK: 3, SIDE: 5})

        self.assertEqual(self._unlock(node_id=12, slot=3), UseOutcome.COUNTED)
        # Another lock inside the window is another use, not a duplicate.
        self.assertEqual(self._unlock(node_id=13, slot=5), UseOutcome.COUNTED)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 2)
        self.assertEqual(code.last_used_lock, SIDE)
        self.assertEqual([(e.lock_entity_id, e.metadata["slot_index"]) for e in self._uses()], [(BACK, 3), (SIDE, 5)])

    def test_the_slot_picks_the_code_on_that_lock(self):
        first = self._code(slots={BACK: 3})
        second = self._code(slots={BACK: 4, SIDE: 3})

        self._unlock(node_id=13, slot=3)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.uses_count, second.uses_count), (0, 1))
        self.assertEqual(second.last_used_lock, SIDE)

    def test_a_use_past_the_limit_is_counted_and_flagged_over_limit(self):
        code = self._code(code_type=DoorCode.CodeType.ONE_TIME)
        self._unlock()
        self._age_uses(60)
        self._unlock()

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 2)
        # Nothing turns it off in this PR.
        self.assertTrue(code.is_active)
        self.assertEqual([e.metadata["over_limit"] for e in self._uses()], [False, True])
        self.assertEqual([e.metadata["max_uses"] for e in self._uses()], [None, None])

    def test_an_unknown_slot_records_a_use_with_no_code(self):
        code = self._code(slots={BACK: 3})

        self.assertEqual(self._unlock(slot=9), UseOutcome.UNMATCHED)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 0)
        (event,) = self._uses()
        self.assertIsNone(event.door_code_id)
        self.assertEqual(event.lock_entity_id, BACK)
        self.assertEqual(event.metadata["slot_index"], 9)
        self.assertEqual(event.metadata["node_id"], 12)
        self.assertTrue(event.metadata["unmatched"])
        # And dedupes like any other.
        self.assertEqual(self._unlock(slot=9), UseOutcome.DUPLICATE)

    def test_a_node_with_no_entity_records_nothing(self):
        self.assertEqual(self._unlock(node_id=99), UseOutcome.UNMATCHED)
        self.assertEqual(self._uses(), [])

    def test_a_lock_on_another_home_id_is_counted_like_the_push_finds_it_with_a_warning(self):
        # The push resolves a lock by node id alone, so a lock it pushes to gets counts.
        _lock_entity("lock.garage", 14, home_id=1)
        code = self._code(slots={"lock.garage": 3})

        self.assertEqual(lock_entity_ids_for_node(node_id=14), ["lock.garage"])
        with self.assertLogs("locks.use_cases.code_usage", level="WARNING") as logs:
            self.assertEqual(self._unlock(node_id=14), UseOutcome.COUNTED)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 1)
        self.assertIn("lock.garage records Z-Wave home id 1", logs.output[0])

    def test_a_lock_on_this_home_id_or_none_recorded_is_counted_without_a_warning(self):
        self._code(slots={BACK: 3, SIDE: 5})
        with self.assertNoLogs("locks.use_cases.code_usage", level="WARNING"):
            self.assertEqual(self._unlock(node_id=12, slot=3), UseOutcome.COUNTED)
            self.assertEqual(self._unlock(node_id=13, slot=5), UseOutcome.COUNTED)

    def test_uses_are_dated_when_they_came_in(self):
        code = self._code()
        received = timezone.now() - timedelta(seconds=30)

        handle_keypad_unlock(KeypadUnlock(node_id=12, slot=3, event=6, received_at=received), home_id=HOME_ID)

        code.refresh_from_db()
        self.assertEqual(code.last_used_at, received)
        self.assertEqual(self._uses()[0].created_at, received)

    def test_two_uses_20s_apart_counted_back_to_back_both_count(self):
        # A row lock held for a while lets both queue up and get counted in the
        # same moment, which used to put them in one dedupe window.
        code = self._code()
        first = timezone.now() - timedelta(seconds=25)
        second = first + timedelta(seconds=20)

        for received_at in (first, second):
            unlock = KeypadUnlock(node_id=12, slot=3, event=6, received_at=received_at)
            self.assertEqual(handle_keypad_unlock(unlock, home_id=HOME_ID), UseOutcome.COUNTED)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 2)
        self.assertEqual(code.last_used_at, second)

    def test_a_repeat_report_counted_late_is_still_the_same_use(self):
        code = self._code()
        first = timezone.now() - timedelta(seconds=60)

        for received_at in (first, first + timedelta(seconds=3)):
            handle_keypad_unlock(KeypadUnlock(node_id=12, slot=3, event=6, received_at=received_at), home_id=HOME_ID)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 1)
        self.assertEqual(code.last_used_at, first)

    def test_two_codes_in_the_slot_on_one_node_are_skipped(self):
        # Two lock entities for the same node, each with a code in slot 3.
        _lock_entity("lock.back_door_2", 12, home_id=HOME_ID)
        first = self._code(slots={BACK: 3})
        second = self._code(slots={"lock.back_door_2": 3})

        with self.assertLogs("locks.use_cases.code_usage", level="WARNING"):
            self.assertEqual(self._unlock(), UseOutcome.AMBIGUOUS)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.uses_count, second.uses_count), (0, 0))
        self.assertEqual(self._uses(), [])


class StaleSlotTests(_UsageTestBase):
    def _fail_clear(self, code: DoorCode, *, lock_entity_id: str = BACK, slot_index: int = 3, removing=False) -> None:
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            expected_pin="9999",
            removing=removing,
        )

    def test_a_slot_with_a_clear_outstanding_is_recorded_stale_and_not_counted(self):
        # A PIN change whose clear of the old PIN failed: the slot may still hold it.
        code = self._code(slots={BACK: 3})
        self._fail_clear(code)

        self.assertEqual(self._unlock(), UseOutcome.STALE_SLOT)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 0)
        self.assertIsNone(code.last_used_at)
        (event,) = self._uses()
        self.assertEqual(event.door_code_id, code.id)
        self.assertTrue(event.metadata["stale_slot"])
        self.assertEqual(event.metadata["stale_reason"], "clear_outstanding")

    def test_a_slot_only_a_failed_clear_knows_about_is_stale_on_that_code(self):
        # The code moved to slot 4, its clear of slot 3 never went through.
        code = self._code(slots={BACK: 4})
        self._fail_clear(code, slot_index=3)

        self.assertEqual(self._unlock(slot=3), UseOutcome.STALE_SLOT)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 0)
        (event,) = self._uses()
        self.assertEqual(event.door_code_id, code.id)
        self.assertTrue(event.metadata["stale_slot"])

    def test_a_settled_clear_is_not_stale(self):
        code = self._code(slots={BACK: 3})
        self._fail_clear(code)
        lock_push_uc.resolve_clear_failure(door_code=code, lock_entity_id=BACK, slot_index=3, outcome="cleared")

        self.assertEqual(self._unlock(), UseOutcome.COUNTED)

    def test_a_code_that_is_off_but_still_holds_its_slot_is_stale(self):
        code = self._code(slots={BACK: 3}, is_active=False)

        self.assertEqual(self._unlock(), UseOutcome.STALE_SLOT)

        code.refresh_from_db()
        self.assertEqual(code.uses_count, 0)
        self.assertEqual(self._uses()[0].metadata["stale_reason"], "inactive")


class RecordKeypadUseRecheckTests(_UsageTestBase):
    def test_a_slot_that_moved_before_the_row_was_taken_is_recorded_with_no_code(self):
        code = self._code(slots={BACK: 3})
        DoorCodeLockAssignment.objects.filter(door_code=code).update(slot_index=4)

        outcome = record_keypad_use(door_code_id=code.id, lock_entity_id=BACK, slot_index=3, notification_event=6)

        self.assertEqual(outcome, UseOutcome.UNMATCHED)
        code.refresh_from_db()
        self.assertEqual(code.uses_count, 0)
        self.assertIsNone(self._uses()[0].door_code_id)

    def test_a_code_deleted_before_the_row_was_taken_is_recorded_with_no_code(self):
        code = self._code(slots={BACK: 3})
        code_id = code.id
        code.delete()

        outcome = record_keypad_use(door_code_id=code_id, lock_entity_id=BACK, slot_index=3, notification_event=6)

        self.assertEqual(outcome, UseOutcome.UNMATCHED)
        self.assertEqual(len(self._uses()), 1)


@skipUnless(connection.vendor == "postgresql", "needs row locks from Postgres")
class ConcurrentUseTests(TransactionTestCase):
    """Uses landing at once each count, and the same use reported at once counts once."""

    LOCKS = [f"lock.door_{n}" for n in range(6)]

    def setUp(self):
        user = User.objects.create_user(email="guest@example.com", password="pass")
        self.code = DoorCode.objects.create(user=user, code_type=DoorCode.CodeType.PERMANENT)
        for n, lock_entity_id in enumerate(self.LOCKS):
            _lock_entity(lock_entity_id, 20 + n, home_id=HOME_ID)
            DoorCodeLockAssignment.objects.create(door_code=self.code, lock_entity_id=lock_entity_id, slot_index=3)

    def _run_at_once(self, calls) -> list:
        barrier = threading.Barrier(len(calls))
        results: list = [None] * len(calls)

        def run(i, call):
            try:
                barrier.wait(timeout=5)
                results[i] = call()
            except Exception as exc:  # pragma: no cover - surfaced by the asserts
                results[i] = exc
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return results

    def test_uses_on_different_locks_at_once_all_count(self):
        def use(lock_entity_id):
            return lambda: record_keypad_use(
                door_code_id=self.code.id, lock_entity_id=lock_entity_id, slot_index=3, notification_event=6
            )

        results = self._run_at_once([use(lock) for lock in self.LOCKS])

        self.assertEqual(results, [UseOutcome.COUNTED] * len(self.LOCKS))
        self.code.refresh_from_db()
        self.assertEqual(self.code.uses_count, len(self.LOCKS))
        counts = sorted(
            DoorCodeEvent.objects.filter(event_type=DoorCodeEvent.EventType.CODE_USED).values_list(
                "metadata__uses_count", flat=True
            )
        )
        self.assertEqual(counts, list(range(1, len(self.LOCKS) + 1)))

    def test_the_same_use_reported_at_once_counts_once(self):
        def use():
            return record_keypad_use(
                door_code_id=self.code.id, lock_entity_id=self.LOCKS[0], slot_index=3, notification_event=6
            )

        results = self._run_at_once([use] * 4)

        self.assertEqual(sorted(results), sorted([UseOutcome.COUNTED] + [UseOutcome.DUPLICATE] * 3))
        self.code.refresh_from_db()
        self.assertEqual(self.code.uses_count, 1)


class KeypadListenerTests(SimpleTestCase):
    """The bridge listener only parses, logs and queues. The worker does the DB work."""

    def _listener(self, worker):
        return locks_runtime.make_event_listener(worker=worker)

    def _msg(self, *, cc_id=113, event=6, parameters=None):
        return {
            "event": {
                "source": "node",
                "event": "notification",
                "nodeId": 12,
                "ccId": cc_id,
                "args": {
                    "type": 6,
                    "label": "Access Control",
                    "event": event,
                    "eventLabel": "Keypad unlock operation",
                    "parameters": parameters or {"userId": 3, "userCode": PIN},
                },
            }
        }

    def test_a_keypad_unlock_is_logged_with_only_the_allowlisted_fields_and_queued(self):
        worker = locks_runtime.KeypadUseWorker()
        before = timezone.now()
        with patch.object(worker, "submit") as submit, self.assertLogs("locks.runtime", level="INFO") as logs:
            self._listener(worker)(self._msg())

        submit.assert_called_once_with(KeypadUnlock(node_id=12, slot=3, event=6))
        (unlock,), _ = submit.call_args
        self.assertGreaterEqual(unlock.received_at, before)
        self.assertEqual(
            logs.output,
            [
                "INFO:locks.runtime:zwavejs keypad event {'nodeId': 12, 'ccId': 113, 'type': 6, 'event': 6, "
                "'eventLabel': 'Keypad unlock operation', 'userId': 3}"
            ],
        )

    def test_no_payload_shape_gets_the_pin_into_the_log(self):
        # Shapes that got past the old redact-known-keys sanitizer, and a few more.
        base = self._msg()["event"]
        shapes = {
            "nested parameters": {"userId": 3, "credential": {"userCode": PIN}},
            "other parameter key": {"userId": 3, "code": PIN, "pin": PIN},
            "userId as the PIN": {"userId": PIN},
            "parameters as a list": [3, PIN],
            "parameters as a string": PIN,
        }
        msgs = [{"event": {**base, "args": {**base["args"], "parameters": value}}} for value in shapes.values()]
        msgs += [
            {"event": {**base, "userCode": PIN, "extra": {"deep": [PIN]}}},
            {"event": {**base, "args": {**base["args"], "eventData": PIN, "userCode": PIN, "value": PIN}}},
            {"event": {**base, "args": {**base["args"], "eventLabel": f"Keypad unlock {PIN}"}}},
            {"event": {**base, "args": {**base["args"], "eventLabel": {"text": PIN}}}},
            {"event": {**base, "args": {**base["args"], "label": PIN, "type": PIN}}},
            {"event": {**base, "nodeId": PIN, "endpointIndex": PIN}},
        ]
        worker = locks_runtime.KeypadUseWorker()
        with patch.object(worker, "submit"), self.assertLogs("locks.runtime", level="INFO") as logs:
            for msg in msgs:
                self._listener(worker)(msg)

        self.assertEqual(len(logs.output), len(msgs))
        for line in logs.output:
            self.assertNotIn(PIN, line)

    def test_a_keypad_lock_is_logged_but_not_queued(self):
        worker = locks_runtime.KeypadUseWorker()
        with patch.object(worker, "submit") as submit, self.assertLogs("locks.runtime", level="INFO"):
            self._listener(worker)(self._msg(event=5))
        submit.assert_not_called()

    def test_other_command_classes_are_not_logged_or_queued(self):
        worker = locks_runtime.KeypadUseWorker()
        with patch.object(worker, "submit") as submit, self.assertNoLogs("locks.runtime", level="INFO"):
            self._listener(worker)(self._msg(cc_id=111))
        submit.assert_not_called()

    def test_the_worker_counts_on_its_own_thread(self):
        worker = locks_runtime.KeypadUseWorker()
        threads: list[str] = []
        unlock = KeypadUnlock(node_id=12, slot=3, event=6)
        with (
            patch(
                "locks.use_cases.code_usage.handle_keypad_unlock",
                side_effect=lambda *_a, **_k: threads.append(threading.current_thread().name),
            ) as handle,
            patch.object(locks_runtime, "_home_id", return_value=HOME_ID),
            patch.object(locks_runtime, "_close_old_connections"),
        ):
            worker.start()
            self.assertTrue(worker.submit(unlock))
            worker.join()

        handle.assert_called_once_with(unlock, home_id=HOME_ID)
        self.assertEqual(threads, ["locks-keypad-uses"])

    def test_a_full_queue_drops_with_a_warning(self):
        worker = locks_runtime.KeypadUseWorker(maxsize=1)
        unlock = KeypadUnlock(node_id=12, slot=3, event=6)
        self.assertTrue(worker.submit(unlock))
        with self.assertLogs("locks.runtime", level="WARNING"):
            self.assertFalse(worker.submit(unlock))


class LocksRuntimeStartupTests(SimpleTestCase):
    def setUp(self):
        locks_runtime._initialized = False
        self.addCleanup(setattr, locks_runtime, "_initialized", False)

    def test_initialize_registers_the_listener_and_starts_the_worker(self):
        manager = type("Manager", (), {})()
        registered = []
        manager.register_event_listener = registered.append
        gateway = type("Gateway", (), {"manager": manager})()
        with (
            patch("alarm.gateways.zwavejs.default_zwavejs_gateway", gateway),
            patch.object(locks_runtime.keypad_use_worker, "start") as start,
        ):
            locks_runtime.initialize()
            locks_runtime.initialize()

        self.assertEqual(len(registered), 1)
        start.assert_called_once_with()

    @override_settings(START_RUNTIMES="auto")
    def test_ready_starts_the_runtime_only_in_the_server(self):
        from types import SimpleNamespace

        from django.apps import apps

        from locks import apps as locks_apps

        def run_ready(argv) -> bool:
            with (
                patch.object(locks_apps, "sys", SimpleNamespace(argv=argv)),
                patch("locks.runtime.initialize") as initialize,
            ):
                apps.get_app_config("locks").ready()
            return initialize.called

        self.assertFalse(run_ready(["manage.py", "shell"]))
        self.assertTrue(run_ready(["daphne", "config.asgi:application"]))
