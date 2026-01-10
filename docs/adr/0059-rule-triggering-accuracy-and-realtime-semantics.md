# ADR 0059: Rule Triggering Accuracy and Realtime Semantics

## Status
Accepted (Partially Implemented)

## Context
ADR 0057 introduced a centralized dispatcher that evaluates only rules impacted by integration entity changes. This substantially improves performance and consistency, but there are known gaps that impact “realtime correctness”:

- **Time semantics drift:** “for: N seconds” scheduling currently uses the evaluation time, not the actual integration event time. Debounce/batching can shift `scheduled_for`.
- **Level-trigger behavior:** A rule can re-fire whenever it is re-evaluated and its `when` remains true (e.g., unrelated entity changes can cause reevaluation).
- **Cross-process cache invalidation:** The dispatcher’s entity→rule cache invalidation is currently in-process only; multi-worker deployments can remain stale until TTL refresh.
- **Non-entity triggers:** Some conditions depend on non-entity signals (e.g., detection feeds, global alarm state) and need a consistent dependency/indexing strategy.

## Decision
Make rule firing more accurate and more immediate by adding the following enhancements on top of ADR 0057:

1. **Event-time evaluation**
   - Propagate `changed_at` from integrations through the dispatcher into rules evaluation.
   - Use batch timestamps when computing “for: N seconds” scheduling and due-runtime decisions.

2. **Edge-triggered firing (opt-in default)**
   - Add runtime tracking so “immediate” rules fire on false→true transitions of `when`, not on every evaluation while `when` stays true.
   - Keep cooldown semantics as an additional guardrail (not a substitute).

3. **Cross-process cache invalidation**
   - Replace in-process-only invalidation with a shared-cache “version” (or last-updated timestamp) key.
   - Each process refreshes its local mapping when the shared version changes.

4. **First-class non-entity dependencies**
   - Introduce a general dependency index (e.g., `RuleDependencyRef`) for non-entity operators, or define clear “synthetic entity” conventions and store them in the same reverse index.
   - Ensure dispatcher routing works for those signals without evaluating unrelated rules.

## Alternatives Considered
- Accept current semantics and rely on cooldowns.
  - Rejected: cooldown hides repeated firing but does not provide correct transition semantics.
- Remove debouncing.
  - Rejected: bursty integrations will cause evaluation stampedes and increased DB load.
- Evaluate “all rules” for any non-entity signal.
  - Rejected: defeats the purpose of ADR 0057 and does not scale.

## Consequences
- More accurate “for” timing and reduced latency drift under debounce/batching.
- More predictable firing behavior (transition-based) and fewer surprises from unrelated updates.
- Slightly more runtime state stored per rule and more complex evaluation logic.
- More robust behavior in multi-worker deployments due to proper cache invalidation.

## Todos
- [x] Implement event-time evaluation in dispatcher/rules engine (`changed_at` → `run_rules(now=...)`)
- [x] Implement shared-cache invalidation/versioning for entity→rule mapping
- Add transition-based runtime tracking:
  - Persist per-rule `when` match state and last transition timestamp.
  - Define behavior for restarts (default to “unknown → evaluate without firing until stable” or similar).
- Add a dependency indexing strategy for non-entity operators and update dispatcher routing accordingly.
- Add tests for:
  - “for” timing with delayed dispatch
  - No refire on repeated evaluations while `when` remains true
  - Cross-process invalidation behavior (version bump triggers refresh)
