"""Tests for token bucket rate limiter."""

import time
from unittest import TestCase

from alarm.dispatcher.rate_limiter import TokenBucket


class TestTokenBucket(TestCase):
    """Tests for TokenBucket rate limiter."""

    def test_initial_burst_available(self):
        """Full burst capacity is available initially."""
        bucket = TokenBucket(rate_per_sec=10, burst=5)
        self.assertEqual(bucket.available_tokens, 5.0)

    def test_acquire_success(self):
        """Acquiring tokens when available succeeds."""
        bucket = TokenBucket(rate_per_sec=10, burst=5)
        self.assertTrue(bucket.acquire(1))
        self.assertTrue(bucket.acquire(2))
        self.assertAlmostEqual(bucket.available_tokens, 2.0, delta=0.1)

    def test_acquire_failure_when_empty(self):
        """Acquiring tokens when depleted fails."""
        bucket = TokenBucket(rate_per_sec=10, burst=2)
        self.assertTrue(bucket.acquire(2))
        self.assertFalse(bucket.acquire(1))

    def test_tokens_refill_over_time(self):
        """Tokens refill at the configured rate."""
        bucket = TokenBucket(rate_per_sec=100, burst=10)
        self.assertTrue(bucket.acquire(10))  # Deplete
        self.assertFalse(bucket.acquire(1))  # Empty

        # Wait for refill
        time.sleep(0.05)  # 5 tokens at 100/sec

        # Should have some tokens now
        self.assertGreater(bucket.available_tokens, 4.0)

    def test_tokens_dont_exceed_burst(self):
        """Token count never exceeds burst limit."""
        bucket = TokenBucket(rate_per_sec=1000, burst=5)
        time.sleep(0.1)  # Would add 100 tokens at 1000/sec
        self.assertEqual(bucket.available_tokens, 5.0)

    def test_reset(self):
        """Reset restores full capacity."""
        bucket = TokenBucket(rate_per_sec=10, burst=5)
        bucket.acquire(5)
        self.assertAlmostEqual(bucket.available_tokens, 0.0, delta=0.1)
        bucket.reset()
        self.assertEqual(bucket.available_tokens, 5.0)

    def test_invalid_params_raise(self):
        """Invalid parameters raise ValueError."""
        with self.assertRaises(ValueError):
            TokenBucket(rate_per_sec=0, burst=5)

        with self.assertRaises(ValueError):
            TokenBucket(rate_per_sec=10, burst=0)

    def test_zero_tokens_always_succeeds(self):
        """Acquiring 0 or negative tokens always succeeds."""
        bucket = TokenBucket(rate_per_sec=10, burst=5)
        bucket.acquire(5)  # Deplete
        self.assertTrue(bucket.acquire(0))
        self.assertTrue(bucket.acquire(-1))
