# ADR 0057: Integration Entity Updates Trigger Rules (Efficiently)

## Status
Accepted (Implemented)

## Context
Rules are the primary automation surface, but rule evaluation is currently inconsistent across integrations:
- Some integrations can run rules on ingest (e.g., MQTT-driven ones), while others only update `Entity` rows and never re-evaluate rules automatically.
- Integrations may produce high volumes of updates (bursty MQTT topics, frequent state changes, many entities), making “run all rules on every event” too expensive.

Operationally, we only care about *changes that could affect a rule outcome*:
- If an integration updates an `Entity` that is not referenced by any enabled rule, we should not spend time evaluating rules.
- If an integration updates an `Entity` that *is* referenced, we want rules to evaluate quickly (near-real-time) and fire as soon as conditions match.

We already have a data model that can support efficient targeting:
- `RuleEntityRef` provides a reverse index from `Entity` → `Rule` for entity-referenced conditions.

This ADR supersedes ADR 0046 by generalizing the “HA updates should trigger rules” requirement into a consistent, integration-wide event-to-rules pipeline.

## Decision
Introduce a centralized, debounced “rule trigger dispatcher” that receives entity state changes (and other integration signals where applicable) and evaluates only the affected rules.

### Core mechanics
- Maintain/expand a reverse index of rule dependencies:
  - Entity dependencies use `RuleEntityRef` (existing).
  - Non-entity dependencies (e.g., integration event streams like Frigate detections) may use a dedicated index (new) or be handled via targeted rule kinds as an interim step.
- When an integration ingests updates:
  1. Upsert affected `Entity` rows and detect *actual state changes*.
  2. Emit a lightweight “entity_changed” trigger with the changed entity IDs.
  3. The dispatcher batches and deduplicates triggers (short debounce window) and resolves impacted rules via `RuleEntityRef`.
  4. Run the rules engine for only those rules (plus timer processing as needed).

### Timing semantics
- Immediate rules: evaluate impacted rules right after the debounce window.
- “for: N seconds” rules: keep the existing timer/runtime mechanism, but ensure due runtimes are processed reliably even without new integration events (periodic “due runtime” task).

## Alternatives Considered
- Run all enabled rules on every entity change.
  - Rejected: too expensive and will not scale with frequent updates.
- Rely solely on periodic polling/sync tasks.
  - Rejected: introduces latency and still does unnecessary work on unchanged/unreferenced entities.
- Push complex per-integration rule evaluation logic into each integration runtime.
  - Rejected: duplicates logic, makes behavior inconsistent, harder to test and evolve.

## Consequences
- Consistent behavior: any connected/enabled integration that updates entities can trigger rules with low latency.
- Scales better: rule evaluation cost is proportional to “rules impacted by changed entities” instead of “all rules”.
- Requires careful debouncing and dedupe to avoid stampedes during bursty ingest.
- Requires observability (counters, last-run timestamps, skipped/debounced counts) to debug and tune.

### Error handling & resilience
- **Per-rule failure tracking:** Track consecutive evaluation failures per rule in `RuleRuntimeState` (new field: `consecutive_failures`).
- **Exponential backoff:** After N consecutive failures (default: 3), skip the rule for increasing intervals (1min → 5min → 15min → 1hr cap). Reset on success.
- **Circuit breaker:** After M consecutive failures (default: 10), mark rule as `error_suspended` and stop evaluating until manually re-enabled or a configurable cooldown (e.g., 1hr) passes.
- **Failure logging:** Log each failure with rule ID, entity IDs, exception, and timestamp. No automatic retry within the same dispatch cycle—wait for next trigger.
- **Health endpoint:** Expose suspended/failing rules count for monitoring dashboards.

### Concurrency & race conditions
- **One evaluation at a time per rule:** Use a lightweight lock (cache-based with TTL, e.g., `rule_eval_lock:{rule_id}`) before evaluating. If lock is held, skip this cycle—the in-progress evaluation will see current state.
- **Rule update during evaluation:** Let the current evaluation complete. The rule's `updated_at` timestamp is checked post-evaluation; if it changed, re-queue for immediate re-evaluation with new definition.
- **Entity state consistency:** Within a single dispatch batch, snapshot entity states at batch start. All rules in that batch see the same consistent view.

### Configuration & tunability
- **Debounce window:** Global default of 200ms, overridable per integration via `IntegrationConfig.dispatcher_debounce_ms`. Range: 50ms–2000ms.
- **Batch size limit:** Max entities per dispatch batch (default: 100). Overflow triggers immediate flush and new batch.
- **Rate limiting:** Token bucket per integration source—default 10 dispatches/sec sustained, burst of 50. Configurable via `IntegrationConfig`.
- **Worker concurrency:** Number of parallel rule evaluations (default: 4 workers). Configurable via settings.

### Default behavior
- **Always enabled:** The dispatcher is the default and only mechanism for triggering rules from entity state changes. All integrations use the dispatcher with no feature flags.
- **Tuning parameters:** Debounce, rate limiting, batch size, and worker concurrency are configurable via system settings for performance tuning if needed.

### Edge cases
- **Deleted entities:** On `Entity` deletion, cascade-delete related `RuleEntityRef` rows (DB foreign key or explicit cleanup). Rules referencing deleted entities will have those refs removed and won't trigger on phantom IDs.
- **Stale refs (orphaned):** Weekly background task scans `RuleEntityRef` for entity IDs not in `Entity` table and removes them. Log count for observability.
- **Re-enabled rules:** When a rule transitions from disabled → enabled, immediately queue a "synthetic" dispatch for all its referenced entity IDs to evaluate against current state.
- **Rule with no entity refs:** Rules that don't reference entities (e.g., time-only triggers) are excluded from entity-triggered dispatch; they rely solely on the periodic timer task.

### Backpressure & bounds
- **Dispatch queue:** Bounded in-memory queue (default max depth: 1000 batches). If full, drop oldest batch and increment `dispatcher_dropped_batches` counter.
- **Debounce cache:** LRU cache with max 10,000 entries and 60s TTL. Entries older than TTL are evicted regardless of LRU position.
- **Worker starvation protection:** If queue depth exceeds 80% for >30s, emit warning log and metric. At 100%, oldest batches are dropped (see above).
- **Graceful degradation:** Under sustained overload, increase debounce window dynamically (up to 2x configured value) to reduce dispatch frequency. Restore when queue drains below 50%.

### Non-entity dependencies (concrete plan)
- **Frigate (interim):** Frigate event ingest notifies dispatcher with a synthetic "source" identifier (e.g., `frigate:detection`). Dispatcher filters to rules with `kind=frigate_detection` instead of using `RuleEntityRef`. This is a targeted carve-out, not a general mechanism.
- **Future work (separate ADR):** If more integrations need non-entity triggers, introduce `RuleDependencyRef` table with polymorphic `dependency_type` (entity, event_stream, webhook, etc.) and `dependency_key`. Out of scope for this ADR.
- **Explicit exclusion:** Integrations that don't update `Entity` rows and don't have a carve-out are not wired to the dispatcher—they retain existing behavior until addressed.

### In-memory caching for rule lookup
- **Problem:** Entity state updates can occur many times per second. Querying `RuleEntityRef` from the database on every batch would create excessive DB load.
- **Solution:** Maintain an in-memory cache of entity_id → rule_id mappings, refreshed periodically.
- **Cache structure:** `dict[str, set[int]]` mapping entity IDs to sets of rule IDs.
- **Refresh interval:** 60 seconds (configurable). Cache is rebuilt entirely on refresh by querying all `RuleEntityRef` rows.
- **Invalidation:** Explicit invalidation via `invalidate_entity_rule_cache()` when rules are created, updated, or deleted. This nullifies the cache timestamp, forcing an immediate refresh on the next dispatcher lookup. Rules are wired to trigger real-time after creation.
- **Thread safety:** Cache access protected by a threading lock to handle concurrent dispatcher calls.
- **60s TTL as fallback:** The 60-second refresh is a safety net for edge cases (e.g., direct DB edits). Normal CRUD operations invalidate immediately.
- **Memory bound:** Cache size is bounded by number of unique entity IDs referenced by rules (typically hundreds to low thousands).

### Testing strategy
- **Unit tests:**
  - Debounce logic: multiple events within window collapse to one dispatch.
  - Dedupe logic: same entity ID in batch appears once.
  - `RuleEntityRef` resolution: correct rules returned for entity IDs.
  - Lock acquisition/skip behavior.
  - Circuit breaker state transitions.
- **Integration tests:**
  - End-to-end: entity update → dispatcher → rule evaluation → action fired.
  - Concurrent entity updates from multiple integrations.
  - Rule update during evaluation triggers re-evaluation.
- **Load tests:**
  - Burst scenario: 1000 entity updates in 100ms, measure dispatch latency and queue depth.
  - Sustained load: 100 updates/sec for 10 minutes, verify no memory growth or dropped batches.
  - Failure cascade: 50% of rules throw exceptions, verify circuit breaker activates and healthy rules continue.

## Todos
### Backend: rule trigger dispatcher
- Add a centralized dispatcher entrypoint (e.g. `notify_entities_changed(source, entity_ids, changed_at=...)`).
- Debounce + dedupe in cache to handle bursts:
  - Avoid repeated runs for the same entity within a short window.
  - Batch multiple entity changes into a single evaluation pass.
- Run in a background worker (thread) to avoid blocking ingest loops.

### Backend: evaluate only impacted rules
- Resolve impacted rule IDs via `RuleEntityRef` for the changed entities and only evaluate those enabled rules.
- Keep ordering semantics (priority) within the impacted set.
- In the same run, process due “for: … seconds” runtimes so timers fire reliably.

### Backend: maintain dependency index (`RuleEntityRef`)
- On rule create/update, extract referenced entities from the rule definition and keep `RuleEntityRef` in sync:
  - Add missing refs, delete stale refs, in the same transaction as the rule update.
- Add a management command to backfill/repair refs for existing rules.

### Backend: timer execution independent of ingest
- Add a periodic scheduled task to process due rule runtimes (`RuleRuntimeState.scheduled_for <= now`) even when no integration events arrive.
- Keep this task lightweight and bounded (only due runtimes).

### Integration wiring (enabled + connected only)
- Home Assistant:
  - Preferred: WS subscription updates `Entity` on `state_changed` and notifies dispatcher for changed entity IDs.
  - Fallback: polling/sync task notifies dispatcher when it detects actual state changes.
- Z-Wave JS:
  - Translate value updates to `Entity` state updates and notify dispatcher for changed entity IDs.
- Zigbee2MQTT:
  - Replace “run all rules” behavior with “notify dispatcher with changed entity IDs”.
- Frigate:
  - If ingest updates `Entity` state, use the dispatcher like other integrations.
  - If rules depend on Frigate detections via repository calls (not entity refs), route through dispatcher with:
    - an interim filter (e.g. by rule kind), and/or
    - a dedicated dependency index for Frigate-backed conditions (longer-term).

### Observability
- Add per-source dispatcher counters: triggered, deduped, debounced, rate-limited, last-run timestamp.
- Add rules-run summary counters for targeted runs: rules evaluated/fired/scheduled/errors.
