"""Core rule trigger dispatcher implementation."""

from __future__ import annotations

import logging
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from .config import DispatcherConfig, get_dispatcher_config
from .failure_handler import is_rule_allowed, record_rule_failure, record_rule_success
from .rate_limiter import TokenBucket
from .stats import DispatcherStats
from .entity_extractor import extract_entity_ids_from_definition

if TYPE_CHECKING:
    from alarm.models import Rule

logger = logging.getLogger(__name__)

# Cache key prefixes
_CACHE_PREFIX = "dispatcher:"
_CACHE_DEBOUNCE_KEY = f"{_CACHE_PREFIX}debounce:"
_CACHE_RULE_LOCK_KEY = f"{_CACHE_PREFIX}rule_lock:"
_CACHE_ENTITY_RULE_VERSION_KEY = f"{_CACHE_PREFIX}entity_rule_cache_version"

# Lock TTL for rule evaluation
_RULE_LOCK_TTL_SECONDS = 30

# In-memory cache for entity -> rule_ids mapping (refreshed periodically)
_entity_rule_cache: dict[str, set[int]] = {}
_entity_rule_cache_lock = threading.Lock()
_entity_rule_cache_updated_at: datetime | None = None
_entity_rule_cache_version: str | None = None
_ENTITY_RULE_CACHE_TTL_SECONDS = 60  # Refresh every 60 seconds


@dataclass
class EntityChangeBatch:
    """A batch of entity changes to be dispatched."""

    source: str
    entity_ids: set[str]
    changed_at: datetime
    batch_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


class RuleDispatcher:
    """
    Centralized dispatcher for rule evaluation based on entity changes.

    Receives entity change notifications from integrations, debounces and
    batches them, then evaluates only the rules that reference those entities.
    """

    def __init__(self, config: DispatcherConfig | None = None):
        """
        Initialize the dispatcher.

        Args:
            config: Optional configuration, will load from settings if not provided
        """
        self._config = config or get_dispatcher_config()
        self._lock = threading.Lock()
        # entity_id -> (first_seen, source) to track which integration notified
        self._pending_entities: dict[str, tuple[datetime, str]] = {}
        self._pending_batches: deque[EntityChangeBatch] = deque(
            maxlen=self._config.queue_max_depth
        )
        self._stats = DispatcherStats()
        self._rate_limiter = TokenBucket(
            rate_per_sec=self._config.rate_limit_per_sec,
            burst=self._config.rate_limit_burst,
        )
        self._worker_pool: ThreadPoolExecutor | None = None
        self._debounce_timer: threading.Timer | None = None
        self._shutdown = False

    def notify_entities_changed(
        self,
        *,
        source: str,
        entity_ids: list[str],
        changed_at: datetime | None = None,
    ) -> None:
        """
        Main entrypoint for integrations to notify of entity changes.

        This method is thread-safe and non-blocking. Changes are batched
        and dispatched after the debounce window.

        Args:
            source: Integration source (e.g., "zigbee2mqtt", "home_assistant")
            entity_ids: List of entity IDs that changed
            changed_at: Optional timestamp of the change (defaults to now)
        """
        if self._shutdown:
            return

        if not entity_ids:
            return

        now = changed_at or timezone.now()
        debounce_ms = self._config.debounce_ms

        with self._lock:
            # Dedupe entity_ids
            unique_ids = set(entity_ids)
            original_count = len(entity_ids)
            if len(unique_ids) < original_count:
                self._stats.record_dedupe(original_count - len(unique_ids))

            # Apply debounce: filter out entities seen within debounce window
            debounced_count = 0
            for entity_id in list(unique_ids):
                cache_key = f"{_CACHE_DEBOUNCE_KEY}{entity_id}"
                last_seen = cache.get(cache_key)
                if last_seen is not None:
                    # Entity was recently notified, skip
                    unique_ids.discard(entity_id)
                    debounced_count += 1
                else:
                    # Mark as seen with debounce TTL
                    cache.set(cache_key, now.isoformat(), timeout=debounce_ms / 1000.0)

            if debounced_count > 0:
                self._stats.record_debounce(source, debounced_count)

            if not unique_ids:
                return

            # Add to pending entities for batch dispatch
            for entity_id in unique_ids:
                if entity_id not in self._pending_entities:
                    self._pending_entities[entity_id] = (now, source)

            # Check batch size limit
            if len(self._pending_entities) >= self._config.batch_size_limit:
                self._flush_batch_locked(source, now)
            else:
                # Schedule flush after debounce window if not already scheduled
                self._schedule_flush_locked(source)

    def _schedule_flush_locked(self, source: str) -> None:
        """Schedule a batch flush after debounce window. Must hold lock."""
        if self._debounce_timer is not None:
            return  # Already scheduled

        def _flush():
            with self._lock:
                self._debounce_timer = None
                if self._pending_entities:
                    # Determine source: use original if all from same source, else "mixed"
                    sources = {s for _, s in self._pending_entities.values()}
                    flush_source = sources.pop() if len(sources) == 1 else "mixed"
                    self._flush_batch_locked(flush_source, timezone.now())

        delay_sec = self._config.debounce_ms / 1000.0
        self._debounce_timer = threading.Timer(delay_sec, _flush)
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

    def _flush_batch_locked(self, source: str, now: datetime) -> None:
        """Flush pending entities as a batch. Must hold lock."""
        if not self._pending_entities:
            return

        # Cancel any pending timer
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
            self._debounce_timer = None

        # Apply rate limiting
        if not self._rate_limiter.acquire():
            self._stats.record_rate_limit()
            logger.debug("Dispatcher rate limited, dropping batch")
            self._pending_entities.clear()
            return

        # Create batch
        batch = EntityChangeBatch(
            source=source,
            entity_ids=set(self._pending_entities.keys()),
            changed_at=now,
        )

        # Append batch to queue (deque with maxlen handles overflow automatically,
        # but we want to log when it happens for visibility)
        if len(self._pending_batches) >= self._config.queue_max_depth:
            self._stats.record_dropped_batch()
            logger.warning("Dispatcher queue full, oldest batch will be dropped")

        self._pending_batches.append(batch)
        self._pending_entities.clear()

        # Record stats
        self._stats.record_trigger(source, len(batch.entity_ids), now)

        # Dispatch to worker pool
        self._ensure_worker_pool()
        if self._worker_pool:
            try:
                self._worker_pool.submit(self._dispatch_batch, batch)
            except RuntimeError as exc:
                # Pool may be shutting down
                logger.warning("Failed to submit batch to worker pool: %s", exc)

    def _ensure_worker_pool(self) -> None:
        """Ensure worker pool is initialized."""
        if self._worker_pool is None:
            self._worker_pool = ThreadPoolExecutor(
                max_workers=self._config.worker_concurrency,
                thread_name_prefix="dispatcher-",
            )

    def _dispatch_batch(self, batch: EntityChangeBatch) -> None:
        """
        Process a batch of entity changes.

        Resolves impacted rules via RuleEntityRef and evaluates them.

        Args:
            batch: The batch to process
        """
        close_old_connections()

        try:
            rules = self._resolve_impacted_rules(batch.entity_ids)
            if not rules:
                logger.debug(
                    "Batch %s: no rules reference entities %s",
                    batch.batch_id,
                    batch.entity_ids,
                )
                return

            logger.debug(
                "Batch %s: evaluating %d rules for %d entities from %s",
                batch.batch_id,
                len(rules),
                len(batch.entity_ids),
                batch.source,
            )

            # Snapshot only the entity states required to evaluate the impacted rules.
            snapshot_started = perf_counter()
            entity_state_map = self._get_entity_state_map_for_rules(
                rules=rules, changed_entity_ids=batch.entity_ids
            )
            snapshot_ms = (perf_counter() - snapshot_started) * 1000.0
            self._stats.record_entity_state_snapshot(size=len(entity_state_map), query_ms=snapshot_ms)

            for rule in rules:
                self._evaluate_rule_with_lock(rule, entity_state_map, batch)

        except Exception as exc:
            logger.exception("Batch %s: dispatch failed: %s", batch.batch_id, exc)

        finally:
            # Remove from pending batches
            with self._lock:
                try:
                    self._pending_batches.remove(batch)
                except ValueError:
                    # Batch was already removed (e.g., by queue overflow or shutdown)
                    pass

    def _resolve_impacted_rules(self, entity_ids: set[str]) -> list[Rule]:
        """
        Find rules referencing the given entities using in-memory cache.

        Uses a cached entity->rule_ids mapping that refreshes every 60 seconds,
        avoiding DB queries on the hot path.

        Args:
            entity_ids: Set of entity IDs that changed

        Returns:
            List of enabled rules ordered by priority (descending)
        """
        from alarm.models import Rule

        # Get rule IDs from cache (refreshes if stale)
        rule_ids = self._get_rule_ids_from_cache(entity_ids)
        if not rule_ids:
            return []

        # Fetch the actual Rule objects (this is cheap - just fetching by PK)
        rules = list(
            Rule.objects.filter(id__in=rule_ids, enabled=True).order_by("-priority", "id")
        )
        return rules

    def _get_rule_ids_from_cache(self, entity_ids: set[str]) -> set[int]:
        """
        Look up rule IDs from the in-memory cache.

        Refreshes the cache if it's stale (older than TTL).
        """
        global _entity_rule_cache, _entity_rule_cache_updated_at
        global _entity_rule_cache_version

        now = timezone.now()

        # Check if cache needs refresh
        with _entity_rule_cache_lock:
            shared_version = self._get_or_init_shared_entity_rule_cache_version()
            last_updated = _entity_rule_cache_updated_at
            needs_refresh = shared_version != _entity_rule_cache_version or (
                last_updated is None
                or (now - last_updated).total_seconds() > _ENTITY_RULE_CACHE_TTL_SECONDS
            )
            if needs_refresh:
                self._refresh_entity_rule_cache()

            # Look up rule IDs for all entity_ids
            rule_ids: set[int] = set()
            for entity_id in entity_ids:
                if entity_id in _entity_rule_cache:
                    rule_ids.update(_entity_rule_cache[entity_id])

        return rule_ids

    def _refresh_entity_rule_cache(self) -> None:
        """
        Rebuild the entity->rule_ids cache from the database.

        Must be called with _entity_rule_cache_lock held.
        """
        global _entity_rule_cache, _entity_rule_cache_updated_at
        global _entity_rule_cache_version

        from alarm.models import RuleEntityRef

        new_cache: dict[str, set[int]] = {}

        # Single query to get all entity->rule mappings
        refs = RuleEntityRef.objects.select_related("entity").values_list(
            "entity__entity_id", "rule_id"
        )

        for entity_id, rule_id in refs:
            if entity_id not in new_cache:
                new_cache[entity_id] = set()
            new_cache[entity_id].add(rule_id)

        _entity_rule_cache = new_cache
        _entity_rule_cache_updated_at = timezone.now()
        _entity_rule_cache_version = self._get_or_init_shared_entity_rule_cache_version()
        logger.debug("Refreshed entity-rule cache: %d entities mapped", len(new_cache))

    def _get_or_init_shared_entity_rule_cache_version(self) -> str:
        """
        Read the shared entity-rule cache version, initializing it if unset.

        Note: this is best-effort; on a per-process cache backend (LocMem), the
        version is effectively in-process, but the logic remains correct.
        """
        try:
            current = cache.get(_CACHE_ENTITY_RULE_VERSION_KEY)
            if isinstance(current, str) and current.strip():
                return current.strip()
            # Initialize once so invalidation has a shared key to bump.
            version = uuid4().hex
            cache.set(_CACHE_ENTITY_RULE_VERSION_KEY, version, timeout=None)
            return version
        except Exception:
            # Fall back to a local-only version; TTL refresh still applies.
            return uuid4().hex

    def _resolve_impacted_rules_uncached(self, entity_ids: set[str]) -> list[Rule]:
        """
        Query RuleEntityRef directly (fallback, not used in hot path).
        """
        from alarm.models import Rule, RuleEntityRef

        # Find rule IDs that reference any of the changed entities
        rule_ids = (
            RuleEntityRef.objects.filter(entity__entity_id__in=entity_ids)
            .values_list("rule_id", flat=True)
            .distinct()
        )

        # Fetch enabled rules ordered by priority
        rules = list(
            Rule.objects.filter(id__in=rule_ids, enabled=True).order_by("-priority", "id")
        )

        return rules

    def _get_entity_state_map(self) -> dict[str, str | None]:
        """Get current entity states as a snapshot."""
        from alarm.models import Entity

        return dict(Entity.objects.values_list("entity_id", "last_state"))

    def _get_entity_state_map_for_rules(
        self,
        *,
        rules: list[Rule],
        changed_entity_ids: set[str],
    ) -> dict[str, str | None]:
        """
        Build an entity-state snapshot for evaluating the given rules.

        Optimization (ADR 0061): fetch only the entity IDs required by impacted rules,
        rather than loading the full Entity table on every batch.
        """
        from alarm.models import Entity, RuleEntityRef

        required: set[str] = set(changed_entity_ids or set())

        # Prefer the dependency index (RuleEntityRef) and augment with a best-effort
        # extraction from the in-memory rule definitions (defensive if refs are stale).
        rule_ids = [int(getattr(r, "id")) for r in rules if getattr(r, "id", None) is not None]
        if rule_ids:
            try:
                ref_entity_ids = RuleEntityRef.objects.filter(rule_id__in=rule_ids).values_list(
                    "entity__entity_id", flat=True
                )
                required.update(str(eid).strip() for eid in ref_entity_ids if str(eid).strip())
            except Exception:
                pass

        for rule in rules:
            try:
                definition = getattr(rule, "definition", None)
                required.update(extract_entity_ids_from_definition(definition))
            except Exception:
                continue

        if not required:
            return {}

        qs = Entity.objects.filter(entity_id__in=sorted(required)).values_list("entity_id", "last_state")
        return dict(qs)

    def _evaluate_rule_with_lock(
        self,
        rule: Rule,
        entity_state_map: dict[str, str | None],
        batch: EntityChangeBatch,
    ) -> None:
        """
        Evaluate a single rule with per-rule locking.

        Args:
            rule: The rule to evaluate
            entity_state_map: Snapshot of entity states
            batch: The batch context
        """
        from alarm import rules_engine
        from alarm.rules.repositories import RuleEngineRepositories, default_rule_engine_repositories

        lock_key = f"{_CACHE_RULE_LOCK_KEY}{rule.id}"

        # Try to acquire lock
        if not cache.add(lock_key, batch.batch_id, timeout=_RULE_LOCK_TTL_SECONDS):
            logger.debug(
                "Rule %s locked, skipping (in-progress evaluation will see current state)",
                rule.id,
            )
            return

        try:
            # Get or create runtime state
            from alarm.models import RuleRuntimeState

            runtime, _ = RuleRuntimeState.objects.get_or_create(
                rule=rule,
                node_id="when",
                defaults={"status": "pending"},
            )

            # Check if rule is allowed (not suspended/backoff)
            now = batch.changed_at or timezone.now()
            if timezone.is_naive(now):
                now = timezone.make_aware(now)
            allowed, reason = is_rule_allowed(runtime=runtime, now=now)
            if not allowed:
                logger.debug("Rule %s skipped: %s", rule.id, reason)
                return

            # Create filtered repositories that only return this rule
            base_repos = default_rule_engine_repositories()

            def _single_rule_list():
                return [rule]

            repos = RuleEngineRepositories(
                list_enabled_rules=_single_rule_list,
                entity_state_map=lambda: entity_state_map,
                due_runtimes=base_repos.due_runtimes,
                ensure_runtime=base_repos.ensure_runtime,
                frigate_is_available=base_repos.frigate_is_available,
                list_frigate_detections=base_repos.list_frigate_detections,
                get_alarm_state=base_repos.get_alarm_state,
            )

            # Run evaluation
            eval_started = perf_counter()
            result = rules_engine.run_rules(now=now, repos=repos)
            eval_ms = (perf_counter() - eval_started) * 1000.0
            self._stats.record_rule_eval_time(eval_ms=eval_ms)
            self._stats.record_rules_result(
                evaluated=result.evaluated,
                fired=result.fired,
                scheduled=result.scheduled,
                errors=result.errors,
            )

            if result.errors > 0:
                record_rule_failure(
                    rule=rule,
                    runtime=runtime,
                    error="Evaluation error (see logs)",
                    now=now,
                )
            else:
                record_rule_success(runtime=runtime)

        except Exception as exc:
            logger.exception("Rule %s evaluation failed: %s", rule.id, exc)
            self._stats.record_rules_result(errors=1)

            # Record failure for circuit breaker
            try:
                from alarm.models import RuleRuntimeState

                runtime, _ = RuleRuntimeState.objects.get_or_create(
                    rule=rule,
                    node_id="when",
                    defaults={"status": "pending"},
                )
                record_rule_failure(
                    rule=rule,
                    runtime=runtime,
                    error=str(exc),
                    now=timezone.now(),
                )
            except Exception as recording_exc:
                # Best-effort: failure to record should not break dispatcher flow
                logger.warning(
                    "Failed to record failure state for rule %s: %s",
                    rule.id,
                    recording_exc,
                )

        finally:
            cache.delete(lock_key)

    def get_status(self) -> dict[str, Any]:
        """Get dispatcher status and statistics."""
        with self._lock:
            return {
                "enabled": True,  # Dispatcher is always enabled (ADR 0057)
                "config": {
                    "debounce_ms": self._config.debounce_ms,
                    "batch_size_limit": self._config.batch_size_limit,
                    "rate_limit_per_sec": self._config.rate_limit_per_sec,
                    "worker_concurrency": self._config.worker_concurrency,
                },
                "pending_entities": len(self._pending_entities),
                "pending_batches": len(self._pending_batches),
                "stats": self._stats.as_dict(),
            }

    def shutdown(self) -> None:
        """Shutdown the dispatcher gracefully."""
        self._shutdown = True

        with self._lock:
            if self._debounce_timer:
                self._debounce_timer.cancel()
                self._debounce_timer = None

        if self._worker_pool:
            self._worker_pool.shutdown(wait=True)
            self._worker_pool = None

    def reload_config(self) -> None:
        """Reload configuration from settings."""
        new_config = get_dispatcher_config()
        with self._lock:
            self._config = new_config
            self._rate_limiter = TokenBucket(
                rate_per_sec=new_config.rate_limit_per_sec,
                burst=new_config.rate_limit_burst,
            )


# Module-level singleton
_dispatcher: RuleDispatcher | None = None
_dispatcher_lock = threading.Lock()


def get_dispatcher() -> RuleDispatcher:
    """Get or create the singleton dispatcher instance."""
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is None:
            _dispatcher = RuleDispatcher()
        return _dispatcher


def notify_entities_changed(
    *,
    source: str,
    entity_ids: list[str],
    changed_at: datetime | None = None,
) -> None:
    """
    Public API to notify the dispatcher of entity changes.

    Args:
        source: Integration source (e.g., "zigbee2mqtt", "home_assistant")
        entity_ids: List of entity IDs that changed
        changed_at: Optional timestamp of the change
    """
    get_dispatcher().notify_entities_changed(
        source=source,
        entity_ids=entity_ids,
        changed_at=changed_at,
    )


def get_dispatcher_status() -> dict[str, Any]:
    """Get dispatcher status and statistics."""
    return get_dispatcher().get_status()


def reload_dispatcher_config() -> None:
    """Reload dispatcher configuration from settings."""
    dispatcher = get_dispatcher()
    dispatcher.reload_config()


def shutdown_dispatcher() -> None:
    """Shutdown the dispatcher gracefully."""
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is not None:
            _dispatcher.shutdown()
            _dispatcher = None


def invalidate_entity_rule_cache() -> None:
    """
    Invalidate the entity->rule cache.

    Call this when rules are created, updated, or deleted to ensure
    the cache is refreshed on the next dispatch.
    """
    global _entity_rule_cache_updated_at
    global _entity_rule_cache_version
    with _entity_rule_cache_lock:
        _entity_rule_cache_updated_at = None
        _entity_rule_cache_version = None
        # Best-effort: bump the shared version to force refresh in other processes.
        try:
            cache.set(_CACHE_ENTITY_RULE_VERSION_KEY, uuid4().hex, timeout=None)
        except Exception:
            pass
    logger.debug("Entity-rule cache invalidated")
