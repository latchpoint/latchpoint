"""Token bucket rate limiter for the dispatcher."""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """
    Thread-safe token bucket rate limiter.

    Allows bursts up to `burst` tokens, refilling at `rate_per_sec` tokens per second.
    """

    def __init__(self, *, rate_per_sec: float, burst: int):
        """
        Initialize the token bucket.

        Args:
            rate_per_sec: Sustained rate of tokens per second
            burst: Maximum burst capacity
        """
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        if burst < 1:
            raise ValueError("burst must be at least 1")

        self._rate_per_sec = rate_per_sec
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time. Must be called with lock held."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate_per_sec)
        self._last_refill = now

    def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens without blocking.

        Args:
            tokens: Number of tokens to acquire (default 1)

        Returns:
            True if tokens were acquired, False if not enough available
        """
        if tokens < 1:
            return True

        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_and_acquire(self, tokens: int = 1, timeout_sec: float = 1.0) -> bool:
        """
        Wait until tokens are available or timeout expires.

        Args:
            tokens: Number of tokens to acquire (default 1)
            timeout_sec: Maximum time to wait in seconds

        Returns:
            True if tokens were acquired, False if timeout expired
        """
        if tokens < 1:
            return True

        deadline = time.monotonic() + timeout_sec

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True

                # Calculate wait time for enough tokens
                tokens_needed = tokens - self._tokens
                wait_time = tokens_needed / self._rate_per_sec

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False

            # Sleep for the shorter of wait_time or remaining timeout
            time.sleep(min(wait_time, remaining, 0.1))

    @property
    def available_tokens(self) -> float:
        """Return the current number of available tokens."""
        with self._lock:
            self._refill()
            return self._tokens

    def reset(self) -> None:
        """Reset the bucket to full capacity."""
        with self._lock:
            self._tokens = float(self._burst)
            self._last_refill = time.monotonic()
