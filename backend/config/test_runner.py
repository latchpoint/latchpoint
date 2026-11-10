"""Test-run hooks shared by `manage.py test` (TEST_RUNNER) and pytest (`backend/conftest.py`)."""

from __future__ import annotations

import time

from django.test.runner import DiscoverRunner
from django.test.utils import iter_test_cases

# How long the drain waits for a running dispatch before it fails the test instead of hanging the run.
DRAIN_TIMEOUT_SECONDS = 10.0
# A running batch can queue another one (`ws_signals` notifies on every alarm state change), so the drain
# repeats until a pass finds nothing. This many passes without that means something keeps queuing.
_MAX_DRAIN_PASSES = 5


def drain_rule_dispatcher() -> None:
    """Stop the rule dispatcher's queued and running work so it can't outlive a test (#210).

    `notify_entities_changed` starts a 200ms debounce timer that hands the batch to a
    worker thread, and that thread reads and writes the database. Left alone they run
    during the next test, or after the test database is gone. A batch still waiting on
    the debounce is dropped, since the test that queued it is over, and its debounce
    keys are cleared so the next test's notify for the same entity isn't skipped. A
    batch already running is waited for, up to `DRAIN_TIMEOUT_SECONDS`, and then the
    test fails naming it. The singleton stays, so the next test doesn't read the
    dispatcher config again, and it makes a new worker pool on its next dispatch.
    """
    from django.core.cache import cache

    from alarm.dispatcher import dispatcher as dispatcher_module

    dispatcher = dispatcher_module._dispatcher
    if dispatcher is None:
        return

    deadline = time.monotonic() + DRAIN_TIMEOUT_SECONDS
    for _ in range(_MAX_DRAIN_PASSES):
        with dispatcher._lock:
            timer, dispatcher._debounce_timer = dispatcher._debounce_timer, None
            pool, dispatcher._worker_pool = dispatcher._worker_pool, None
            dropped = set(dispatcher._pending_entities)
            dispatcher._pending_entities.clear()
            queued = {e for batch in dispatcher._pending_batches for e in batch.entity_ids}
        if timer is None and pool is None and not dropped:
            return

        cache.delete_many([f"{dispatcher_module._CACHE_DEBOUNCE_KEY}{e}" for e in dropped | queued])
        if timer is not None:
            # A timer that already fired waits on the lock, then finds nothing pending.
            timer.cancel()
            timer.join(timeout=max(0.0, deadline - time.monotonic()))
            if timer.is_alive():
                raise AssertionError(
                    f"The rule dispatcher's debounce timer was still running {DRAIN_TIMEOUT_SECONDS:g}s after the test"
                )
        if pool is not None:
            pool.shutdown(wait=False)
            for thread in list(pool._threads):
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if any(thread.is_alive() for thread in pool._threads):
                raise AssertionError(_describe_stuck_batches(dispatcher))

    raise AssertionError(f"The rule dispatcher was still queuing batches after {_MAX_DRAIN_PASSES} drain passes")


def _describe_stuck_batches(dispatcher) -> str:
    with dispatcher._lock:
        batches = list(dispatcher._pending_batches)
    described = (
        "; ".join(f"batch {b.batch_id} from {b.source} for {', '.join(sorted(b.entity_ids))}" for b in batches)
        or "a batch that isn't in the queue"
    )
    return (
        f"A rule dispatch was still running {DRAIN_TIMEOUT_SECONDS:g}s after the test ({described}). "
        "It may be waiting on a lock held by the test's own transaction."
    )


class LatchpointTestRunner(DiscoverRunner):
    """Drains the rule dispatcher after every test.

    It's a cleanup on each test so it runs before Django rolls back or flushes the
    test's database, while the rows a running dispatch reads are still there.
    """

    def load_tests_for_label(self, label, discover_kwargs):
        tests = super().load_tests_for_label(label, discover_kwargs)
        for test in iter_test_cases(tests):
            test.addCleanup(drain_rule_dispatcher)
        return tests
