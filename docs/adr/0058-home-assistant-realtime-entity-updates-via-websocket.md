# ADR 0058: Home Assistant Realtime Entity Updates via WebSocket (Dispatcher-Based)

## Status
Proposed

## Context
We currently learn about Home Assistant (HA) entity state changes via periodic polling in `sync_entity_states` (`backend/alarm/tasks.py`), which adds latency to rules that depend on HA entities.

The rules pipeline introduced in ADR 0057 is designed around integrations emitting `notify_entities_changed(...)` once `Entity.last_state` has been updated. HA should feed that same pipeline, but in near-real-time.

We already keep the polling task as a correctness safety net (ADR 0027): it repairs missed events after disconnects/restarts. The realtime path should be primary, with polling as fallback.

## Decision
Add a persistent backend → HA WebSocket subscription to `state_changed` events and wire it into the ADR 0057 dispatcher:

1. Establish a WebSocket connection to HA at `/api/websocket`.
2. Authenticate with the configured long-lived token.
3. `subscribe_events` for `state_changed`.
4. On each `state_changed` event:
   - Update the matching `alarm.models.Entity` row (only for `source="home_assistant"`).
   - If the state actually changed, call `alarm.dispatcher.notify_entities_changed(source="home_assistant", entity_ids=[entity_id], changed_at=<event_time>)`.

### Concurrency / multi-process
In production, multiple Django/Daphne processes may exist. To avoid N duplicated HA connections, implement a lightweight leader lock in shared cache:
- Only the leader maintains the HA WebSocket connection.
- Non-leaders periodically attempt to acquire leadership (or remain idle).

### Failure handling
- Reconnect with exponential backoff and jitter.
- If disconnected, rely on ADR 0027 polling as fallback to correct stale states.

## Alternatives Considered
- Lower the polling interval.
  - Rejected: higher HA load and still not truly realtime.
- Rely on MQTT state topics from HA.
  - Deferred: requires additional HA configuration and MQTT availability.
- HA automations calling back into this app (webhooks).
  - Rejected: shifts complexity and reliability burden to user configuration.

## Consequences
- HA-backed rules evaluate with low latency (bounded mostly by dispatcher debounce and worker scheduling).
- Additional complexity: persistent connection lifecycle, leader election, reconnect logic.
- Polling remains necessary as a safety net; realtime alone is not sufficient for correctness.

## Todos
- Implement HA WebSocket manager under `backend/integrations_home_assistant/`:
  - Connect/auth/subscribe to `state_changed`
  - Reconnect/backoff
  - Shared-cache leader lock
- Wire event handler to:
  - Update `Entity` state/timestamps
  - Call `notify_entities_changed(..., changed_at=...)`
- Add tests:
  - Event → `Entity` update + dispatcher notification
  - Leader lock prevents duplicate connections
- Update docs/config:
  - Clarify polling is fallback-only when realtime subscription is enabled.

