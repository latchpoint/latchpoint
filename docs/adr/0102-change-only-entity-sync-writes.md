# ADR-0102: Change-Only Entity Sync Writes with Coarse last_seen Refresh

**Status:** Proposed
**Date:** 2026-07-21
**Author:** Leonardo Merza

## Context

### Background

GitHub issue [#79](https://github.com/latchpoint/latchpoint/issues/79): the
`sync_entity_states` scheduled task issues one `UPDATE` per Home Assistant
entity on **every** sync pass, whether or not anything changed. On a live
deployment with ~11,900 HA entities and the default 300s interval this
produced **42.5M row updates in 8.7 days** (~3,500 rewrites per row), with
`n_tup_hot_upd = 0` — every update also rewrote index entries. Measured
impact: ~47 GB/day of Postgres block writes, ~14.8 GB/day of container
network traffic, and ~6.5% sustained idle CPU on both app and DB containers.

### Current State

- `backend/alarm/tasks.py::sync_entity_states` (registered at
  `Every(seconds=300, jitter=30)`) loops over
  `Entity.objects.filter(source="home_assistant")`, seeds
  `update_fields = ["last_seen"]`, and calls
  `entity.save(update_fields=...)` **unconditionally** for every entity
  present in the HA state dump — one round-trip per entity, ~11.9k per pass.
- `Entity.last_seen` (`backend/alarm/models.py:296`) is declared with
  `db_index=True`. Because every sync write touches this indexed column,
  **no update can be HOT** — each one rewrites index entries in addition to
  the heap. This is the direct cause of the `n_tup_hot_upd = 0` observation
  in the issue.
- **`last_seen` has no query consumers.** A repo-wide search finds no
  `filter()`, `order_by()`, or raw SQL touching `last_seen` — the index has
  zero readers. The field itself is only *displayed*: exposed by
  `backend/alarm/serializers/entities.py` and rendered in the debug-only
  `EntityStateInspector.tsx` frontend panel.
- The HA WebSocket state stream
  (`backend/integrations_home_assistant/state_stream.py::_handle_state_changed`)
  already stamps `last_state` / `last_changed` / `last_seen` per entity in
  real time via a targeted `queryset.update()` whenever HA pushes a state
  event. The 300s sync pass is a **reconciliation backstop**, not the
  primary freshness path.
- Changed entities additionally fan out to `broadcast_entity_sync` (WebSocket)
  and `notify_entities_changed` (rules dispatcher, ADR-0057). This fan-out
  already only fires for actual changes and must not change.

### Requirements

- Steady-state sync passes (nothing changed, `last_seen` fresh) must issue
  **zero** row writes.
- Database round-trips per pass must be bounded by a small constant, not by
  entity count.
- Genuine state changes must still persist `last_state`, `last_changed`,
  `last_seen`, broadcast over WebSocket, and notify the rules dispatcher —
  identical observable behavior to today.
- `last_seen` must remain a per-entity API field (the debug inspector and
  any external API consumers keep working), and must still converge for
  entities that never emit state events.
- Remaining periodic writes should be HOT-eligible (no index churn).

### Constraints

- The rules engine consumes entity changes through the dispatcher; its
  semantics (ADR-0057/0059) must be untouched.
- `Entity` rows are also written by the Z-Wave JS and Zigbee2MQTT sync paths
  and by `sync_entities_from_home_assistant` (import use case); this ADR
  only changes the periodic HA reconciliation task plus the `last_seen`
  index. Other write paths are out of scope.
- Existing tests in `backend/alarm/tests/test_sync_entity_states.py` encode
  the task's observable contract (return dict shape, broadcast behavior,
  `last_seen` stamped from `NULL`); they must keep passing, with updates
  only where they assert the *write mechanism* rather than behavior.

## Options Considered

### Option 1: Minimal guard, no migration

**Description:** Move the per-entity `save()` inside the
`last_state != new_state` branch; refresh `last_seen` for **all** seen
entities with a single `queryset.update(last_seen=now)` per pass.

**Pros:**
- Smallest diff; no schema migration
- Round-trips drop from ~11,900 to ~2 per pass; network/CPU problem solved

**Cons:**
- Still ~11.9k row versions per pass (~3.4M/day) — dead tuples and index
  churn remain because `last_seen` keeps its index and is rewritten every
  pass
- The headline problem of issue #79 (write amplification / SSD wear) is
  only half-fixed

### Option 2: Change-only writes + coarse last_seen refresh + drop the index (chosen)

**Description:** Persist changed rows with one `bulk_update`; refresh
`last_seen` in one bulk `queryset.update()` **only** for seen rows whose
`last_seen` is `NULL` or older than a staleness threshold (default 1 hour);
drop the unused `db_index=True` from `Entity.last_seen` so the remaining
writes are HOT-eligible.

**Pros:**
- Round-trips: ~11,900 → ≤2 per pass; steady-state passes write **zero** rows
- Row writes: ~3.4M/day → ~150k/day (≈96% cut) at the reference deployment
- Index drop removes the forced non-HOT updates (the `n_tup_hot_upd = 0`
  amplification) at zero read cost — the index has no readers
- `last_seen` stays per-entity and still converges for quiet entities

**Cons:**
- Requires a schema migration (index drop)
- `last_seen` is now accurate only to ~1h for entities with no state events
  (acceptable: its only consumer is a debug display, and the WebSocket
  stream keeps active entities fresh in real time)

### Option 3: Drop per-row last_seen from the sync pass entirely

**Description:** The sync pass stops writing `last_seen` altogether; a
single per-integration "last sync at" timestamp covers liveness. The
WebSocket stream still stamps `last_seen` on real events.

**Pros:**
- Fewest possible writes — steady-state passes touch zero rows with no
  staleness bookkeeping

**Cons:**
- Changes field semantics: a quiet entity's `last_seen` freezes at its last
  real event and can read as days stale in the debug inspector
- API behavior change for any external consumer of `last_seen`
- Larger conceptual change than the issue calls for

## Decision

**Chosen Option:** Option 2 — change-only writes, coarse `last_seen`
refresh, and dropping the `last_seen` index.

**Rationale:** Option 1 fixes round-trips but leaves ~3.4M daily row
rewrites — the actual write-amplification complaint — in place. Option 3
fixes everything but silently changes the meaning of an API field. Option 2
eliminates both the round-trip storm and the write amplification while
keeping `last_seen`'s observable contract (per-entity, converges, never
regresses); the index drop is free because the index provably has no
readers. The 1-hour staleness threshold bounds worst-case `last_seen` drift
to one twelfth of a day for entities that emit no events, which is well
within what a debug display needs.

### Design sketch

In `sync_entity_states` (`backend/alarm/tasks.py`):

1. Iterate entities as today (optionally with `.only()` on the five fields
   the loop touches, trimming the per-pass read of the `attributes` JSON).
2. For changed entities: set `last_state` / `last_changed` / `last_seen` on
   the instance, collect it, and persist all changed rows with one
   `Entity.objects.bulk_update(changed, ["last_state", "last_changed",
   "last_seen"])` after the loop.
3. For unchanged-but-stale entities (`last_seen IS NULL` or
   `last_seen < now - LAST_SEEN_REFRESH_SECONDS`): collect pks and issue one
   `Entity.objects.filter(pk__in=stale_pks).update(last_seen=now)`.
   `LAST_SEEN_REFRESH_SECONDS = 3600` as a module constant (promotable to a
   SystemConfig key later if anyone needs to tune it).
4. Unchanged-and-fresh entities: no write at all.
5. Broadcast / dispatcher fan-out is unchanged (changed entities only).
6. Return dict keeps `synced` / `updated` / `errors` semantics and adds
   `last_seen_refreshed` for observability.

Migration: `AlterField` on `Entity.last_seen` removing `db_index=True`
(a `DROP INDEX` — trivial at this table size).

## Acceptance Criteria

- [ ] **AC-1**: Given N unchanged entities whose `last_seen` is fresh
  (within the staleness threshold), when `sync_entity_states` runs, zero
  `UPDATE` statements are issued and the total query count is constant
  (does not grow with N).
- [ ] **AC-2**: Given M entities with changed states, when the task runs,
  all M rows persist their new `last_state`, a non-null `last_changed`, and
  a refreshed `last_seen` via a single `bulk_update` (query count constant
  in M), and the return dict reports `updated == M`.
- [ ] **AC-3**: Given an unchanged entity whose `last_seen` is `NULL` or
  older than the threshold, when the task runs, its `last_seen` is set to
  the pass timestamp via one bulk `UPDATE`, and the return dict's
  `last_seen_refreshed` counts it.
- [ ] **AC-4**: Given an unchanged entity whose `last_seen` is within the
  threshold, when the task runs, the row's `last_seen` value is unchanged
  afterwards.
- [ ] **AC-5**: Given a state change, when the task runs,
  `broadcast_entity_sync` receives exactly the changed entities (old/new
  state) and `notify_entities_changed` is invoked — and neither is called
  when nothing changed (existing tests keep passing).
- [ ] **AC-6**: A migration exists that removes `db_index=True` from
  `Entity.last_seen`; `makemigrations --check` is clean afterwards and the
  field is otherwise unchanged.
- [ ] **AC-7**: The disabled / not-configured / unreachable / fetch-error
  early-exit paths return the same dicts as before (existing tests
  unmodified).
- [ ] **AC-8**: `synced` still counts entities present in both the local
  registry and the HA dump, even when no rows were written.

## Consequences

### Positive

- Steady-state DB write load from entity sync drops to zero; worst case
  (hourly refresh) is ~150k row writes/day instead of ~3.4M at the
  reference deployment.
- ≤2 write round-trips per pass removes the ~1 KB × 11.9k UPDATE traffic
  every 300s (~the container's dominant idle TX).
- Remaining `last_seen`-only writes become HOT-eligible after the index
  drop, ending the 100% index-rewrite amplification.
- `updated` / broadcast / dispatcher behavior is bit-for-bit what it was.

### Negative

- `last_seen` for event-silent entities is now hourly-granular (was
  300s-granular). Its only known consumer is the debug entity inspector.
- One more migration for prod to run.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| A future feature wants to query stale entities by `last_seen` | Low | Low | Re-add the index in that feature's migration; document here that it was dropped as reader-less |
| Query-count assertions (AC-1/AC-2) prove brittle across Django versions | Medium | Low | Use `assertNumQueries` against the task's own queries with the gateway mocked; count only what the task controls |
| `pk__in` list for the hourly refresh is large (~12k ints once/hour) | Low | Low | Integer pk list is ~100 KB once per hour; acceptable. Chunk if it ever grows past ~50k |
| Ordering: bulk refresh could resurrect rows deleted mid-pass | Low | Low | `filter(pk__in=...)` simply matches fewer rows; no correctness issue |

## Implementation Plan

- [ ] Phase 1: Extend `backend/alarm/tests/test_sync_entity_states.py` with
  AC-1–AC-4/AC-8 cases (query-count assertions, staleness fixtures) — red.
- [ ] Phase 2: Rewrite the write path in `sync_entity_states`
  (`backend/alarm/tasks.py`) per the design sketch — green.
- [ ] Phase 3: Model change + migration dropping the `last_seen` index
  (AC-6).
- [ ] Phase 4: `ruff check` / `ruff format`, full backend suite, update the
  ADR index.

## Related ADRs

- [ADR-0057](./0057-integration-entity-updates-trigger-rules.md) — the
  dispatcher fan-out this task feeds; its contract is preserved.
- [ADR-0058](./0058-home-assistant-realtime-entity-updates-via-websocket.md) —
  the realtime path that makes this task a reconciliation backstop.
- [ADR-0093](./0093-scheduler-instance-id-stable-default.md) — scheduler
  registration conventions for this task.

## References

- [Issue #79 — sync_entity_states writes every entity on every pass](https://github.com/latchpoint/latchpoint/issues/79)
- Issue #80 (scheduler polling volume) is the remaining idle-load floor once
  this lands; intentionally out of scope here.
- Postgres HOT updates: [https://www.postgresql.org/docs/current/storage-hot.html](https://www.postgresql.org/docs/current/storage-hot.html)
