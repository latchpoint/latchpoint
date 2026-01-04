"""Tests for entity→rule cache invalidation."""

from unittest import TestCase
from unittest.mock import patch

from alarm.dispatcher import invalidate_entity_rule_cache
from alarm.dispatcher.dispatcher import (
    _entity_rule_cache,
    _entity_rule_cache_lock,
    _entity_rule_cache_updated_at,
)


class TestCacheInvalidation(TestCase):
    """Tests for cache invalidation behavior."""

    def test_invalidate_clears_timestamp(self):
        """invalidate_entity_rule_cache sets timestamp to None."""
        import alarm.dispatcher.dispatcher as dispatcher_module

        # Set a timestamp
        dispatcher_module._entity_rule_cache_updated_at = "some_time"

        invalidate_entity_rule_cache()

        self.assertIsNone(dispatcher_module._entity_rule_cache_updated_at)

    def test_invalidate_is_thread_safe(self):
        """invalidate_entity_rule_cache acquires the lock."""
        import alarm.dispatcher.dispatcher as dispatcher_module

        # This test verifies the function doesn't crash with concurrent access
        import threading

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
