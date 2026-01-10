# ADR 0061: Optimize Dispatcher Entity-State Snapshot for Faster Rule Evaluation

## Status
Proposed

## Context
The ADR 0057 dispatcher evaluates only rules impacted by entity changes, but it currently snapshots *all* entity states on each dispatched batch:

- `RuleDispatcher._get_entity_state_map()` uses `Entity.objects.values_list("entity_id", "last_state")` for the entire table.
- This is consistent and simple, but it becomes increasingly expensive as the number of entities grows (especially if only a small subset of entities are referenced by rules).

We already optimize rule selection via an in-memory reverse index (`entity_id -> rule_ids`), but the evaluation path can still be dominated by:
- database work to read the full entity-state map, and
- CPU/memory to build that map repeatedly.

## Decision
Change the dispatcher evaluation flow to build a *minimal* entity-state snapshot per batch:

1. Resolve impacted rules for the changed entity IDs (existing behavior).
2. Determine the set of entity IDs required to evaluate those rules:
   - Primary: `RuleEntityRef` entity_ids for the impacted rules (or an equivalent precomputed mapping).
   - Include changed entity IDs even if they are missing from refs (defensive).
3. Fetch `Entity.last_state` only for the required entity IDs and build `entity_state_map` from that reduced query.
4. Evaluate impacted rules against that reduced map.

This keeps the “evaluate against a DB-consistent snapshot” property, while reducing query volume and per-batch work.

## Priority
**High priority.** This optimization targets the current hot-path bottleneck for “state change → rule evaluation” latency.

It is especially impactful when:
- the system has a large entity registry (e.g., ~1000+ entities synced from Home Assistant), and
- only a small subset of entities are referenced by rules (e.g., ~50 entities).

In that scenario, the current “snapshot all entities” behavior does ~20× more DB reads and Python work per batch than necessary.

### Follow-up (optional)
If further optimization is required, consider a second stage:
- Cache enabled rule definitions (and pre-parsed condition trees) in-memory with a shared-cache version bump on rule CRUD.
- Do **not** mirror all entity states in-memory as a first step; correctness and multi-process invalidation are complex and high-risk.

## Alternatives Considered
- Keep the full entity snapshot.
  - Pros: simplest, consistent, no dependency tracking required.
  - Cons: cost grows linearly with total entities, not with “entities relevant to rules”.
- Maintain an in-memory entity-state store.
  - Pros: fastest reads.
  - Cons: hard correctness problems in multi-process deployments; requires reliable cross-process updates, replay on restart, and drift correction.
- Cache only rule evaluation results.
  - Rejected: depends on complete dependency tracking and still needs state reads; risks incorrect caching when conditions depend on time/external repositories.

## Consequences
- Faster “state change → rule evaluation” on installations with many entities but relatively few rule-referenced entities.
- Lower DB read load per dispatched batch.
- Slightly more complexity in the dispatcher due to “required entity IDs” calculation.
- Requires care for non-entity operators (e.g., alarm state, frigate detections): those should not rely on the entity-state map anyway.

## Todos
- Add a helper to compute required entity IDs for an impacted rule set:
  - Use `RuleEntityRef` for impacted rules (efficient query).
  - Include changed entity IDs (defensive).
- Update dispatcher batch execution to fetch `Entity.last_state` only for required entity IDs.
- Add tests:
  - Dispatcher does not query all entities when only one rule is impacted.
  - Correct behavior when an entity ID is changed but missing from `RuleEntityRef`.
- Add metrics:
  - `entity_state_snapshot_size` per batch
  - timing for snapshot query and rule evaluation
