"""Test-run hooks shared by `manage.py test` (TEST_RUNNER) and pytest (`backend/conftest.py`)."""

from __future__ import annotations

from django.test.runner import DiscoverRunner
from django.test.utils import iter_test_cases


def drain_rule_dispatcher() -> None:
    """Stop the rule dispatcher's queued and running work so it can't outlive a test (#210).

    `notify_entities_changed` starts a 200ms debounce timer that hands the batch to a
    worker thread, and that thread reads and writes the database. Left alone they run
    during the next test, or after the test database is gone. A batch still waiting on
    the debounce is dropped, since the test that queued it is over. A batch already
    running is waited for. The singleton stays, so the next test doesn't read the
    dispatcher config again, and it makes a new worker pool on its next dispatch.
    """
    from alarm.dispatcher import dispatcher as dispatcher_module

    dispatcher = dispatcher_module._dispatcher
    if dispatcher is None:
        return

    with dispatcher._lock:
        timer, dispatcher._debounce_timer = dispatcher._debounce_timer, None
        dispatcher._pending_entities.clear()
    if timer is not None:
        # A timer that already fired waits on the lock, then finds nothing pending.
        timer.cancel()
        timer.join()

    with dispatcher._lock:
        pool, dispatcher._worker_pool = dispatcher._worker_pool, None
    if pool is not None:
        pool.shutdown(wait=True)


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
