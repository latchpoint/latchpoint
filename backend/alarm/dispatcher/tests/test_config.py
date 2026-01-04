"""Tests for dispatcher configuration."""

from django.test import TestCase

from alarm.dispatcher.config import (
    DispatcherConfig,
    normalize_dispatcher_config,
)


class TestNormalizeDispatcherConfig(TestCase):
    """Tests for normalize_dispatcher_config function."""

    def test_empty_input_returns_defaults(self):
        """Empty or None input returns default config."""
        config = normalize_dispatcher_config(None)
        self.assertEqual(config.debounce_ms, 200)
        self.assertEqual(config.batch_size_limit, 100)
        self.assertEqual(config.rate_limit_per_sec, 10)
        self.assertEqual(config.rate_limit_burst, 50)
        self.assertEqual(config.worker_concurrency, 4)
        self.assertEqual(config.queue_max_depth, 1000)

    def test_valid_config(self):
        """Valid config values are normalized correctly."""
        raw = {
            "debounce_ms": 500,
            "batch_size_limit": 50,
            "rate_limit_per_sec": 20,
            "rate_limit_burst": 100,
            "worker_concurrency": 8,
            "queue_max_depth": 500,
        }
        config = normalize_dispatcher_config(raw)
        self.assertEqual(config.debounce_ms, 500)
        self.assertEqual(config.batch_size_limit, 50)
        self.assertEqual(config.rate_limit_per_sec, 20)
        self.assertEqual(config.rate_limit_burst, 100)
        self.assertEqual(config.worker_concurrency, 8)
        self.assertEqual(config.queue_max_depth, 500)

    def test_debounce_ms_clamped_to_range(self):
        """debounce_ms is clamped to valid range (50-2000)."""
        # Too low
        config = normalize_dispatcher_config({"debounce_ms": 10})
        self.assertEqual(config.debounce_ms, 50)

        # Too high
        config = normalize_dispatcher_config({"debounce_ms": 5000})
        self.assertEqual(config.debounce_ms, 2000)

        # Valid
        config = normalize_dispatcher_config({"debounce_ms": 300})
        self.assertEqual(config.debounce_ms, 300)

    def test_worker_concurrency_clamped(self):
        """worker_concurrency is clamped to valid range (1-16)."""
        config = normalize_dispatcher_config({"worker_concurrency": 0})
        self.assertEqual(config.worker_concurrency, 1)

        config = normalize_dispatcher_config({"worker_concurrency": 100})
        self.assertEqual(config.worker_concurrency, 16)

    def test_batch_size_limit_clamped(self):
        """batch_size_limit is clamped to valid range (1-1000)."""
        config = normalize_dispatcher_config({"batch_size_limit": 0})
        self.assertEqual(config.batch_size_limit, 1)

        config = normalize_dispatcher_config({"batch_size_limit": 2000})
        self.assertEqual(config.batch_size_limit, 1000)

    def test_queue_max_depth_minimum(self):
        """queue_max_depth has a minimum of 10."""
        config = normalize_dispatcher_config({"queue_max_depth": 5})
        self.assertEqual(config.queue_max_depth, 10)

    def test_rate_limits_minimum(self):
        """Rate limit values have a minimum of 1."""
        config = normalize_dispatcher_config({
            "rate_limit_per_sec": 0,
            "rate_limit_burst": 0,
        })
        self.assertEqual(config.rate_limit_per_sec, 1)
        self.assertEqual(config.rate_limit_burst, 1)

    def test_non_dict_input(self):
        """Non-dict input returns default config."""
        config = normalize_dispatcher_config("invalid")
        self.assertEqual(config.debounce_ms, 200)

        config = normalize_dispatcher_config([1, 2, 3])
        self.assertEqual(config.debounce_ms, 200)

        config = normalize_dispatcher_config(42)
        self.assertEqual(config.debounce_ms, 200)
