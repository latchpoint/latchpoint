from __future__ import annotations

import unittest

import pytest


@pytest.fixture(autouse=True)
def _drain_rule_dispatcher(request):
    """pytest's side of `config.test_runner.LatchpointTestRunner`: no dispatcher work outlives a test (#210)."""
    from config.test_runner import drain_rule_dispatcher

    if isinstance(request.instance, unittest.TestCase):
        # A cleanup runs inside the test, before Django rolls back or flushes its database.
        request.instance.addCleanup(drain_rule_dispatcher)
        yield
    else:
        yield
        drain_rule_dispatcher()
