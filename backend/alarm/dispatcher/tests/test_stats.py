"""Tests for dispatcher statistics."""

from datetime import datetime
from unittest import TestCase

from django.utils import timezone

from alarm.dispatcher.stats import DispatcherStats, SourceStats


class TestSourceStats(TestCase):
    """Tests for SourceStats dataclass."""

    def test_default_values(self):
        """Default values are zero/None."""
        stats = SourceStats()
        self.assertEqual(stats.triggered, 0)
        self.assertEqual(stats.entities_received, 0)
        self.assertEqual(stats.debounced, 0)
        self.assertIsNone(stats.last_dispatch_at)

    def test_as_dict(self):
        """as_dict serializes correctly."""
        now = timezone.now()
        stats = SourceStats(
            triggered=5,
            entities_received=100,
            debounced=20,
            last_dispatch_at=now,
        )
        result = stats.as_dict()
        self.assertEqual(result["triggered"], 5)
        self.assertEqual(result["entities_received"], 100)
        self.assertEqual(result["debounced"], 20)
        self.assertEqual(result["last_dispatch_at"], now.isoformat())


class TestDispatcherStats(TestCase):
    """Tests for DispatcherStats dataclass."""

    def test_default_values(self):
        """Default values are zero/None."""
        stats = DispatcherStats()
        self.assertEqual(stats.triggered, 0)
        self.assertEqual(stats.deduped, 0)
        self.assertEqual(stats.debounced, 0)
        self.assertEqual(stats.rate_limited, 0)
        self.assertEqual(stats.dropped_batches, 0)
        self.assertIsNone(stats.last_dispatch_at)
        self.assertEqual(stats.by_source, {})

    def test_record_trigger(self):
        """record_trigger updates counters correctly."""
        stats = DispatcherStats()
        now = timezone.now()

        stats.record_trigger("zigbee2mqtt", 5, now)

        self.assertEqual(stats.triggered, 1)
        self.assertEqual(stats.last_dispatch_at, now)
        self.assertIn("zigbee2mqtt", stats.by_source)
        self.assertEqual(stats.by_source["zigbee2mqtt"].triggered, 1)
        self.assertEqual(stats.by_source["zigbee2mqtt"].entities_received, 5)

    def test_record_debounce(self):
        """record_debounce updates counters correctly."""
        stats = DispatcherStats()

        stats.record_debounce("frigate", 3)

        self.assertEqual(stats.debounced, 3)
        self.assertIn("frigate", stats.by_source)
        self.assertEqual(stats.by_source["frigate"].debounced, 3)

    def test_record_dedupe(self):
        """record_dedupe updates counter correctly."""
        stats = DispatcherStats()

        stats.record_dedupe(10)

        self.assertEqual(stats.deduped, 10)

    def test_record_rate_limit(self):
        """record_rate_limit updates counter correctly."""
        stats = DispatcherStats()

        stats.record_rate_limit(2)

        self.assertEqual(stats.rate_limited, 2)

    def test_record_dropped_batch(self):
        """record_dropped_batch updates counter correctly."""
        stats = DispatcherStats()

        stats.record_dropped_batch()

        self.assertEqual(stats.dropped_batches, 1)

    def test_record_rules_result(self):
        """record_rules_result updates counters correctly."""
        stats = DispatcherStats()

        stats.record_rules_result(evaluated=10, fired=3, scheduled=2, errors=1)

        self.assertEqual(stats.rules_evaluated, 10)
        self.assertEqual(stats.rules_fired, 3)
        self.assertEqual(stats.rules_scheduled, 2)
        self.assertEqual(stats.rules_errors, 1)

    def test_as_dict(self):
        """as_dict serializes all fields correctly."""
        stats = DispatcherStats()
        now = timezone.now()
        stats.record_trigger("zigbee2mqtt", 5, now)
        stats.record_dedupe(2)

        result = stats.as_dict()

        self.assertEqual(result["triggered"], 1)
        self.assertEqual(result["deduped"], 2)
        self.assertIn("by_source", result)
        self.assertIn("zigbee2mqtt", result["by_source"])

    def test_reset(self):
        """reset clears all counters."""
        stats = DispatcherStats()
        stats.record_trigger("zigbee2mqtt", 5, timezone.now())
        stats.record_dedupe(10)

        stats.reset()

        self.assertEqual(stats.triggered, 0)
        self.assertEqual(stats.deduped, 0)
        self.assertEqual(stats.by_source, {})
        self.assertIsNone(stats.last_dispatch_at)

    def test_multiple_sources(self):
        """Multiple sources are tracked independently."""
        stats = DispatcherStats()
        now = timezone.now()

        stats.record_trigger("zigbee2mqtt", 10, now)
        stats.record_trigger("frigate", 5, now)
        stats.record_trigger("zigbee2mqtt", 3, now)

        self.assertEqual(stats.triggered, 3)
        self.assertEqual(stats.by_source["zigbee2mqtt"].triggered, 2)
        self.assertEqual(stats.by_source["zigbee2mqtt"].entities_received, 13)
        self.assertEqual(stats.by_source["frigate"].triggered, 1)
        self.assertEqual(stats.by_source["frigate"].entities_received, 5)
