# ADR 0057: Integration Entity Updates Trigger Rules (Efficiently)

## Status
Proposed

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
