"""Dispatcher configuration dataclass and settings normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DispatcherConfig:
    """Configuration for the rule trigger dispatcher (always enabled)."""

    debounce_ms: int = 200  # 50-2000ms range
    batch_size_limit: int = 100
    rate_limit_per_sec: int = 10
    rate_limit_burst: int = 50
    worker_concurrency: int = 4
    queue_max_depth: int = 1000


@dataclass(frozen=True)
class IntegrationDispatcherOverride:
    """Per-integration dispatcher configuration overrides."""

    debounce_ms: int | None = None
    rate_limit_per_sec: int | None = None


def normalize_dispatcher_config(raw: Any) -> DispatcherConfig:
    """
    Normalize raw settings dict into a typed DispatcherConfig.

    Args:
        raw: Raw settings value (dict or None)

    Returns:
        Validated DispatcherConfig with defaults applied
    """
    if not isinstance(raw, dict):
        return DispatcherConfig()

    debounce_ms = raw.get("debounce_ms", 200)
    if not isinstance(debounce_ms, int) or debounce_ms < 50:
        debounce_ms = 50
    elif debounce_ms > 2000:
        debounce_ms = 2000

    batch_size_limit = raw.get("batch_size_limit", 100)
    if not isinstance(batch_size_limit, int) or batch_size_limit < 1:
        batch_size_limit = 1
    elif batch_size_limit > 1000:
        batch_size_limit = 1000

    rate_limit_per_sec = raw.get("rate_limit_per_sec", 10)
    if not isinstance(rate_limit_per_sec, int) or rate_limit_per_sec < 1:
        rate_limit_per_sec = 1

    rate_limit_burst = raw.get("rate_limit_burst", 50)
    if not isinstance(rate_limit_burst, int) or rate_limit_burst < 1:
        rate_limit_burst = 1

    worker_concurrency = raw.get("worker_concurrency", 4)
    if not isinstance(worker_concurrency, int) or worker_concurrency < 1:
        worker_concurrency = 1
    elif worker_concurrency > 16:
        worker_concurrency = 16

    queue_max_depth = raw.get("queue_max_depth", 1000)
    if not isinstance(queue_max_depth, int) or queue_max_depth < 10:
        queue_max_depth = 10

    return DispatcherConfig(
        debounce_ms=debounce_ms,
        batch_size_limit=batch_size_limit,
        rate_limit_per_sec=rate_limit_per_sec,
        rate_limit_burst=rate_limit_burst,
        worker_concurrency=worker_concurrency,
        queue_max_depth=queue_max_depth,
    )


def get_dispatcher_config() -> DispatcherConfig:
    """
    Load dispatcher configuration from system settings.

    Returns:
        DispatcherConfig loaded from database settings
    """
    from alarm.state_machine.settings import get_system_config_value

    raw = get_system_config_value("dispatcher")
    return normalize_dispatcher_config(raw)
