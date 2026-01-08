"""Failure handling and circuit breaker logic for rule evaluation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alarm.models import Rule, RuleRuntimeState

logger = logging.getLogger(__name__)

# Exponential backoff schedule: 1min, 5min, 15min, 1hr (cap)
BACKOFF_SCHEDULE_SECONDS = [60, 300, 900, 3600]

# Circuit breaker threshold: suspend after this many consecutive failures
CIRCUIT_BREAKER_THRESHOLD = 10

# Auto-recovery cooldown: suspended rules can retry after this period
AUTO_RECOVERY_SECONDS = 3600  # 1 hour


def get_backoff_seconds(consecutive_failures: int) -> int:
    """
    Get the backoff delay for a given number of consecutive failures.

    Args:
        consecutive_failures: Number of consecutive failures (1-based)

    Returns:
        Backoff delay in seconds
    """
    if consecutive_failures < 1:
        return 0
    idx = min(consecutive_failures - 1, len(BACKOFF_SCHEDULE_SECONDS) - 1)
    return BACKOFF_SCHEDULE_SECONDS[idx]


def record_rule_failure(
    *,
    rule: Rule,
    runtime: RuleRuntimeState,
    error: str,
    now: datetime,
) -> None:
    """
    Record a rule evaluation failure.

    Increments failure counter, computes backoff delay, and potentially
    suspends the rule if circuit breaker threshold is reached.

    Args:
        rule: The rule that failed
        runtime: The runtime state to update
        error: Error message (will be truncated to 500 chars)
        now: Current timestamp
    """
    runtime.consecutive_failures += 1
    runtime.last_failure_at = now
    # Truncate error message and indicate truncation if needed
    if error and len(error) > 500:
        runtime.last_error = error[:497] + "..."
    else:
        runtime.last_error = error or ""

    if runtime.consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
        runtime.error_suspended = True
        runtime.status = "error_suspended"  # Sync status field with error_suspended flag
        runtime.next_allowed_at = now + timedelta(seconds=AUTO_RECOVERY_SECONDS)
        logger.warning(
            "Rule %s (id=%s) suspended after %d consecutive failures: %s",
            rule.name,
            rule.id,
            runtime.consecutive_failures,
            error[:100],
        )
    else:
        backoff_secs = get_backoff_seconds(runtime.consecutive_failures)
        runtime.next_allowed_at = now + timedelta(seconds=backoff_secs)
        logger.info(
            "Rule %s (id=%s) backing off for %ds after %d failures",
            rule.name,
            rule.id,
            backoff_secs,
            runtime.consecutive_failures,
        )

    runtime.save(
        update_fields=[
            "consecutive_failures",
            "last_failure_at",
            "last_error",
            "error_suspended",
            "status",
            "next_allowed_at",
            "updated_at",
        ]
    )


def record_rule_success(*, runtime: RuleRuntimeState) -> None:
    """
    Record a successful rule evaluation.

    Resets failure counters and clears suspension status.

    Args:
        runtime: The runtime state to update
    """
    if runtime.consecutive_failures > 0 or runtime.error_suspended:
        runtime.consecutive_failures = 0
        runtime.last_failure_at = None
        runtime.next_allowed_at = None
        runtime.error_suspended = False
        runtime.last_error = ""
        runtime.save(
            update_fields=[
                "consecutive_failures",
                "last_failure_at",
                "next_allowed_at",
                "error_suspended",
                "last_error",
                "updated_at",
            ]
        )


def is_rule_allowed(*, runtime: RuleRuntimeState, now: datetime) -> tuple[bool, str]:
    """
    Check if a rule is allowed to be evaluated.

    Args:
        runtime: The runtime state to check
        now: Current timestamp

    Returns:
        Tuple of (allowed, reason). If not allowed, reason explains why.
    """
    if runtime.error_suspended:
        # Check for auto-recovery
        if runtime.next_allowed_at and now >= runtime.next_allowed_at:
            return True, "auto_recovery"
        return False, "suspended"

    if runtime.next_allowed_at and now < runtime.next_allowed_at:
        remaining = (runtime.next_allowed_at - now).total_seconds()
        return False, f"backoff:{remaining:.0f}s"

    return True, "allowed"


def clear_suspension(*, runtime: RuleRuntimeState) -> None:
    """
    Manually clear a rule's suspension status.

    Use this when an admin wants to force-retry a suspended rule.

    Args:
        runtime: The runtime state to update
    """
    runtime.consecutive_failures = 0
    runtime.last_failure_at = None
    runtime.next_allowed_at = None
    runtime.error_suspended = False
    runtime.last_error = ""
    runtime.save(
        update_fields=[
            "consecutive_failures",
            "last_failure_at",
            "next_allowed_at",
            "error_suspended",
            "last_error",
            "updated_at",
        ]
    )
    logger.info("Cleared suspension for rule runtime %s", runtime.id)
