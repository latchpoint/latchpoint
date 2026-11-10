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

    def test_drops_a_batch_still_waiting_on_the_debounce(self):
        from config.test_runner import drain_rule_dispatcher

        dispatched = []
        with patch.object(self.dispatcher, "_dispatch_batch", dispatched.append):
            notify_entities_changed(source="test", entity_ids=[_entity_id()])
            timer = self.dispatcher._debounce_timer
            self.assertIsNotNone(timer)

            drain_rule_dispatcher()
            # Past the 200ms debounce, so a timer that survived would have fired by now.
            time.sleep(0.3)

        self.assertFalse(timer.is_alive())
        self.assertIsNone(self.dispatcher._debounce_timer)
        self.assertEqual(self.dispatcher._pending_entities, {})
        self.assertEqual(dispatched, [])

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
            notify_entities_changed(source="test", entity_ids=[entity_id])
            # Fire the debounce now instead of waiting 200ms for it.
            with self.dispatcher._lock:
                self.dispatcher._flush_batch_locked("test", self.dispatcher._pending_entities[entity_id][0])
            self.assertTrue(started.wait(timeout=5))
            workers = list(self.dispatcher._worker_pool._threads)

            drain_rule_dispatcher()

        self.assertEqual(finished, [{entity_id}])
        self.assertIsNone(self.dispatcher._worker_pool)
        self.assertEqual([t.name for t in workers if t.is_alive()], [])

    def test_the_next_dispatch_still_runs(self):
        from config.test_runner import drain_rule_dispatcher

        dispatched = threading.Event()
        with patch.object(self.dispatcher, "_dispatch_batch", lambda batch: dispatched.set()):
            notify_entities_changed(source="test", entity_ids=[_entity_id()])
            drain_rule_dispatcher()
            notify_entities_changed(source="test", entity_ids=[_entity_id()])

            self.assertTrue(dispatched.wait(timeout=5))

    def test_does_nothing_before_the_dispatcher_exists(self):
        from config.test_runner import drain_rule_dispatcher

        with patch.object(dispatcher_module, "_dispatcher", None):
            drain_rule_dispatcher()

            self.assertIsNone(dispatcher_module._dispatcher)
