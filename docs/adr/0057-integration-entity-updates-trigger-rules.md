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
- Add a backend “rule trigger dispatcher” that accepts `changed_entity_ids` and runs only impacted rules.
- Ensure rule save/update maintains `RuleEntityRef` accurately for all entity-referencing condition nodes.
- Add a periodic task to process due rule runtimes (“for: …” timers) independent of integration events.
- Integration wiring (enabled + connected):
  - Home Assistant: on `Entity` state changes (via WS subscription when available; polling as fallback), trigger dispatcher for changed entity IDs.
  - Z-Wave JS: on value/entity state updates, trigger dispatcher for changed entity IDs.
  - Zigbee2MQTT: on entity state updates, trigger dispatcher (replace global rule runs with targeted runs).
  - Frigate: on detection ingest, trigger dispatcher for the subset of rules that depend on Frigate conditions (initially via rule kind filtering; later via a dedicated dependency index if needed).
- Add metrics/debug counters per integration and for the dispatcher: triggered, debounced, rate-limited, rules evaluated/fired.

