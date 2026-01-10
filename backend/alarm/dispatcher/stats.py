"""Observability counters and statistics for the dispatcher."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SourceStats:
    """Per-source statistics."""

    triggered: int = 0
    entities_received: int = 0
    debounced: int = 0
    last_dispatch_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "triggered": self.triggered,
            "entities_received": self.entities_received,
            "debounced": self.debounced,
            "last_dispatch_at": self.last_dispatch_at.isoformat() if self.last_dispatch_at else None,
        }


@dataclass
class DispatcherStats:
    """Global dispatcher statistics."""

    triggered: int = 0
    deduped: int = 0
    debounced: int = 0
    rate_limited: int = 0
    dropped_batches: int = 0
    rules_evaluated: int = 0
    rules_fired: int = 0
    rules_scheduled: int = 0
    rules_errors: int = 0
    last_dispatch_at: datetime | None = None

    # Snapshot / evaluation metrics (ADR 0061 follow-up).
    entity_state_snapshot_size_last: int = 0
    entity_state_snapshot_size_total: int = 0
    snapshot_query_ms_last: float = 0.0
    snapshot_query_ms_total: float = 0.0
    rule_eval_ms_last: float = 0.0
    rule_eval_ms_total: float = 0.0

    by_source: dict[str, SourceStats] = field(default_factory=dict)

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_trigger(self, source: str, entity_count: int, now: datetime) -> None:
        """Record a successful dispatch trigger."""
        with self._lock:
            self.triggered += 1
            self.last_dispatch_at = now

            if source not in self.by_source:
                self.by_source[source] = SourceStats()
            src_stats = self.by_source[source]
            src_stats.triggered += 1
            src_stats.entities_received += entity_count
            src_stats.last_dispatch_at = now

    def record_debounce(self, source: str, count: int = 1) -> None:
        """Record debounced entity changes."""
        with self._lock:
            self.debounced += count
            if source not in self.by_source:
                self.by_source[source] = SourceStats()
            self.by_source[source].debounced += count

    def record_dedupe(self, count: int = 1) -> None:
        """Record deduplicated entities within a batch."""
        with self._lock:
            self.deduped += count

    def record_rate_limit(self, count: int = 1) -> None:
        """Record rate-limited dispatches."""
        with self._lock:
            self.rate_limited += count

    def record_dropped_batch(self, count: int = 1) -> None:
        """Record dropped batches due to queue overflow."""
        with self._lock:
            self.dropped_batches += count

    def record_rules_result(
        self, evaluated: int = 0, fired: int = 0, scheduled: int = 0, errors: int = 0
    ) -> None:
        """Record rule evaluation results."""
        with self._lock:
            self.rules_evaluated += evaluated
            self.rules_fired += fired
            self.rules_scheduled += scheduled
            self.rules_errors += errors

    def record_entity_state_snapshot(self, *, size: int, query_ms: float) -> None:
        """Record entity-state snapshot size and query duration (ms)."""
        size_i = int(size) if isinstance(size, int) else 0
        query_f = float(query_ms) if isinstance(query_ms, (int, float)) else 0.0
        if size_i < 0:
            size_i = 0
        if query_f < 0:
            query_f = 0.0
        with self._lock:
            self.entity_state_snapshot_size_last = size_i
            self.entity_state_snapshot_size_total += size_i
            self.snapshot_query_ms_last = query_f
            self.snapshot_query_ms_total += query_f

    def record_rule_eval_time(self, *, eval_ms: float) -> None:
        """Record rule evaluation duration (ms)."""
        eval_f = float(eval_ms) if isinstance(eval_ms, (int, float)) else 0.0
        if eval_f < 0:
            eval_f = 0.0
        with self._lock:
            self.rule_eval_ms_last = eval_f
            self.rule_eval_ms_total += eval_f

    def as_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for API/monitoring."""
        with self._lock:
            return {
                "triggered": self.triggered,
                "deduped": self.deduped,
                "debounced": self.debounced,
                "rate_limited": self.rate_limited,
                "dropped_batches": self.dropped_batches,
                "rules_evaluated": self.rules_evaluated,
                "rules_fired": self.rules_fired,
                "rules_scheduled": self.rules_scheduled,
                "rules_errors": self.rules_errors,
                "last_dispatch_at": (
                    self.last_dispatch_at.isoformat() if self.last_dispatch_at else None
                ),
                "entity_state_snapshot_size_last": self.entity_state_snapshot_size_last,
                "entity_state_snapshot_size_total": self.entity_state_snapshot_size_total,
                "snapshot_query_ms_last": self.snapshot_query_ms_last,
                "snapshot_query_ms_total": self.snapshot_query_ms_total,
                "rule_eval_ms_last": self.rule_eval_ms_last,
                "rule_eval_ms_total": self.rule_eval_ms_total,
                "by_source": {k: v.as_dict() for k, v in self.by_source.items()},
            }

    def reset(self) -> None:
        """Reset all counters (for testing)."""
        with self._lock:
            self.triggered = 0
            self.deduped = 0
            self.debounced = 0
            self.rate_limited = 0
            self.dropped_batches = 0
            self.rules_evaluated = 0
            self.rules_fired = 0
            self.rules_scheduled = 0
            self.rules_errors = 0
            self.last_dispatch_at = None
            self.entity_state_snapshot_size_last = 0
            self.entity_state_snapshot_size_total = 0
            self.snapshot_query_ms_last = 0.0
            self.snapshot_query_ms_total = 0.0
            self.rule_eval_ms_last = 0.0
            self.rule_eval_ms_total = 0.0
            self.by_source.clear()
