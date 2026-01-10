"""Tests for entity→rule cache invalidation."""

import threading
from unittest import TestCase

import alarm.dispatcher.dispatcher as dispatcher_module
from alarm.dispatcher import invalidate_entity_rule_cache


class TestCacheInvalidation(TestCase):
    """Tests for cache invalidation behavior."""

    def test_invalidate_clears_timestamp(self):
        """invalidate_entity_rule_cache sets timestamp to None."""
        # Set a timestamp
        dispatcher_module._entity_rule_cache_updated_at = "some_time"
        dispatcher_module._entity_rule_cache_version = "some_version"

        invalidate_entity_rule_cache()

        self.assertIsNone(dispatcher_module._entity_rule_cache_updated_at)
        self.assertIsNone(dispatcher_module._entity_rule_cache_version)

    def test_invalidate_is_thread_safe(self):
        """invalidate_entity_rule_cache acquires the lock."""
        # This test verifies the function doesn't crash with concurrent access
        results = []

        def invalidate_many():
            for _ in range(100):
                invalidate_entity_rule_cache()
            results.append(True)

        threads = [threading.Thread(target=invalidate_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 5)
        self.assertIsNone(dispatcher_module._entity_rule_cache_updated_at)
        self.assertIsNone(dispatcher_module._entity_rule_cache_version)
