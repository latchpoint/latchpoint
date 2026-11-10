"""The rule dispatcher's work must not outlive the test that queued it (#210).

`notify_entities_changed` starts a debounce timer that hands the batch to a worker
thread. Both have to be gone by the time the next test starts, or they run against
that test's tables, or against no database at all.
"""

from __future__ import annotations

import threading
import time
import uuid
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from alarm.dispatcher import dispatcher as dispatcher_module
from alarm.dispatcher.config import DispatcherConfig
from alarm.dispatcher.dispatcher import RuleDispatcher, get_dispatcher, notify_entities_changed


def _entity_id() -> str:
    # Unique per call, so the dispatcher's debounce cache never skips it.
    return f"binary_sensor.drain_{uuid.uuid4().hex}"


class NothingOutlivesTheTestTests(TestCase):
    """Runs in name order: the first test queues a dispatch, the second checks it's gone."""

    def test_1_queues_a_dispatch(self):
        notify_entities_changed(source="test", entity_ids=[_entity_id()])

        self.assertIsNotNone(get_dispatcher()._debounce_timer)

    def test_2_nothing_from_an_earlier_test_is_still_running(self):
        dispatcher = get_dispatcher()

        self.assertIsNone(dispatcher._debounce_timer)
        self.assertIsNone(dispatcher._worker_pool)


class DrainRuleDispatcherTests(SimpleTestCase):
    def setUp(self):
        self.dispatcher = RuleDispatcher(config=DispatcherConfig())
        patcher = patch.object(dispatcher_module, "_dispatcher", self.dispatcher)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.dispatcher.shutdown)

    def _dispatch_now(self, entity_id: str) -> None:
        """Queue `entity_id` and fire the debounce now instead of waiting 200ms for it."""
        notify_entities_changed(source="test", entity_ids=[entity_id])
        with self.dispatcher._lock:
            self.dispatcher._flush_batch_locked("test", self.dispatcher._pending_entities[entity_id][0])

    def test_drops_a_batch_still_waiting_on_the_debounce(self):
        from config.test_runner import drain_rule_dispatcher

        dispatched = []
        with patch.object(self.dispatcher, "_dispatch_batch", dispatched.append):
            notify_entities_changed(source="test", entity_ids=[_entity_id()])
            timer = self.dispatcher._debounce_timer
            self.assertIsNotNone(timer)

            drain_rule_dispatcher()

            # Right away, not after the debounce, or a timer the drain never stopped passes too.
            self.assertFalse(timer.is_alive())
            # Past the 200ms debounce, so a timer that survived would have fired by now.
            time.sleep(0.3)

        self.assertIsNone(self.dispatcher._debounce_timer)
        self.assertEqual(self.dispatcher._pending_entities, {})
        self.assertEqual(dispatched, [])

    def test_clears_the_debounce_for_the_entities_it_drops(self):
        from config.test_runner import drain_rule_dispatcher

        entity_id = _entity_id()
        with patch.object(self.dispatcher, "_dispatch_batch", lambda batch: None):
            notify_entities_changed(source="test", entity_ids=[entity_id])
            drain_rule_dispatcher()

            # Inside the 200ms debounce, so a key left behind would skip this notify.
            notify_entities_changed(source="test", entity_ids=[entity_id])

        self.assertIn(entity_id, self.dispatcher._pending_entities)

    def test_waits_for_a_batch_already_running(self):
        from config.test_runner import drain_rule_dispatcher

        started = threading.Event()
        finished = []

        def slow_dispatch(batch):
            started.set()
            time.sleep(0.2)
            finished.append(batch.entity_ids)

        entity_id = _entity_id()
        with patch.object(self.dispatcher, "_dispatch_batch", slow_dispatch):
            self._dispatch_now(entity_id)
            self.assertTrue(started.wait(timeout=5))
            workers = list(self.dispatcher._worker_pool._threads)

            drain_rule_dispatcher()

        self.assertEqual(finished, [{entity_id}])
        self.assertIsNone(self.dispatcher._worker_pool)
        self.assertEqual([t.name for t in workers if t.is_alive()], [])

    def test_also_stops_a_batch_queued_by_a_running_batch(self):
        """A running dispatch can notify again, like `ws_signals` does on an alarm state change."""
        from config.test_runner import drain_rule_dispatcher

        started = threading.Event()
        dispatched = []
        follow_up = _entity_id()

        def dispatch_that_notifies(batch):
            dispatched.append(batch.entity_ids)
            if follow_up not in batch.entity_ids:
                started.set()
                # Late enough that the drain has already taken the timer and is waiting on the pool.
                time.sleep(0.1)
                self.dispatcher.notify_entities_changed(source="alarm_state", entity_ids=[follow_up])

        first = _entity_id()
        with patch.object(self.dispatcher, "_dispatch_batch", dispatch_that_notifies):
            self._dispatch_now(first)
            self.assertTrue(started.wait(timeout=5))

            drain_rule_dispatcher()

            self.assertIsNone(self.dispatcher._debounce_timer)
            self.assertIsNone(self.dispatcher._worker_pool)
            # Past the 200ms debounce, so the follow-up would have run by now if it survived.
            time.sleep(0.3)

        self.assertEqual(dispatched, [{first}])

    def test_fails_the_test_naming_a_batch_that_never_finishes(self):
        from config.test_runner import drain_rule_dispatcher

        release = threading.Event()
        started = threading.Event()

        def stuck_dispatch(batch):
            started.set()
            release.wait(timeout=30)

        entity_id = _entity_id()
        with patch.object(self.dispatcher, "_dispatch_batch", stuck_dispatch):
            self._dispatch_now(entity_id)
            self.assertTrue(started.wait(timeout=5))
            workers = list(self.dispatcher._worker_pool._threads)
            self.addCleanup(lambda: [t.join(timeout=5) for t in workers])
            self.addCleanup(release.set)
            [batch] = self.dispatcher._pending_batches

            began = time.monotonic()
            with (
                patch("config.test_runner.DRAIN_TIMEOUT_SECONDS", 0.2),
                self.assertRaisesMessage(AssertionError, f"batch {batch.batch_id} from test for {entity_id}"),
            ):
                drain_rule_dispatcher()

        self.assertLess(time.monotonic() - began, 5)

    def test_the_next_dispatch_runs_on_a_new_pool(self):
        from config.test_runner import drain_rule_dispatcher

        dispatched = []
        ran = threading.Semaphore(0)

        def record(batch):
            dispatched.append(batch.entity_ids)
            ran.release()

        before, after = _entity_id(), _entity_id()
        with patch.object(self.dispatcher, "_dispatch_batch", record):
            self._dispatch_now(before)
            self.assertTrue(ran.acquire(timeout=5))
            old_pool = self.dispatcher._worker_pool

            drain_rule_dispatcher()
            self.assertIsNone(self.dispatcher._worker_pool)

            notify_entities_changed(source="test", entity_ids=[after])
            self.assertTrue(ran.acquire(timeout=5))

        self.assertEqual(dispatched, [{before}, {after}])
        self.assertIsNotNone(self.dispatcher._worker_pool)
        self.assertIsNot(self.dispatcher._worker_pool, old_pool)

    def test_does_nothing_before_the_dispatcher_exists(self):
        from config.test_runner import drain_rule_dispatcher

        with patch.object(dispatcher_module, "_dispatcher", None):
            drain_rule_dispatcher()

            self.assertIsNone(dispatcher_module._dispatcher)
