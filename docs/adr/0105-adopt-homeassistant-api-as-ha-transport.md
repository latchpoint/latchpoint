# ADR-0105: Adopt `homeassistant-api` as the Home Assistant Transport

**Status:** Proposed
**Date:** 2026-07-25
**Author:** Leonardo Merza

## Context

### Background

Cleaning up recurring Home Assistant log noise after ADR-0103 revealed that this
project has never actually used the `homeassistant_api` library it depends on.

Prod emitted **1,558** `HA status: client check failed; falling back to raw HTTP`
warnings in ~10.7 hours — one roughly every 25 seconds, out of 56,612 total log
lines. Investigating the warning rather than silencing it showed the message was
not describing resilience working as designed. It was reporting a defect, on
every call, forever.

`impl.py` carried three `homeassistant_api` client branches, each presented as the
preferred path with raw HTTP as a fallback. **None of them ever executed
successfully**, and each failure was swallowed by a broad `except`:

| Function | Why the client branch was dead | Removed in |
|----------|--------------------------------|------------|
| `call_service` | Called `client.call_service()`, which does not exist — the library exposes `trigger_service`. Raised `AttributeError` every call. | PR #78 |
| `get_status` | `api_url` defect (below) → `ProcessorNotFoundError` every call | PR #86 |
| `list_entities` | Same `api_url` defect | PR #86 |

**The `api_url` defect.** Both surviving branches passed our bare `base_url` as the
library's first constructor argument. That argument is named `api_url` and is used
verbatim as the endpoint prefix — the library never inserts `/api`. So
`client.get_config()` requested `{base_url}/config`, which is Home Assistant's
Single Page App route. Verified against the live instance:

```
GET http://<ha>:8123/config      -> 200 text/html    <- what the client hit
GET http://<ha>:8123/api/config  -> 401 text/plain   <- REST API; JSON once authorized
```

The library registers response processors for `application/json`,
`application/octet-stream` and `text/plain` — but not `text/html`. Hence
`ProcessorNotFoundError: No response processor found for mimetype 'text/html'` on
every call, then the fall-through to REST.

**Fixing the URL was tried and rejected.** PR #85 corrected it and was closed
unmerged. `list_entities` contains two independent parsers, and the library types
`State.last_changed` as `datetime.datetime` where the REST path yields the raw
JSON string. Activating the client would have silently changed that field's type
in every row feeding `sync_entity_states` → the `Entity` table the alarm's sensors
read. The `except Exception` cannot catch it, because that is the client
*succeeding* with a different shape rather than raising. The branches were deleted
instead (PR #86), which is why the URL defect no longer exists to fix.

### Current State

REST over `urllib` is the single transport for every Home Assistant call:

- `backend/integrations_home_assistant/impl.py` — **529 lines**, with 45
  hand-rolled `urlopen` / `Request` / `json.loads` / `isinstance` sites. Public
  surface: `get_status`, `ensure_available`, `list_entities`, `call_service`,
  `list_services`, `list_service_catalog`, `list_notify_services`.
- `backend/integrations_home_assistant/state_stream.py` — **332 lines** of
  hand-rolled websocket protocol (auth handshake, subscribe, reconnect).
- `requirements.txt:12` carries `homeassistant-api` **unpinned**, and since PR #86
  it is an **entirely unused dependency**.

That is ~860 lines of transport code implementing our own content-type validation,
HTTP error mapping, and per-field type guarding.

### Requirements

1. Home Assistant status, entity listing, service calls, service catalog, and
   notify-service discovery must keep working with no behavior change observable
   by the alarm, the rules engine, or the UI.
2. Row shapes returned to callers must remain byte-identical until a change is
   explicitly intended and verified — the `Entity` table feeds sensors, which
   arm and trigger the alarm.
3. Explicit per-call timeouts must be preserved (currently 2s for status, 5s for
   entities/services).
4. The domain exceptions `HomeAssistantNotConfigured` and
   `HomeAssistantNotReachable` must still be raised at the same boundaries.
5. PR #78's 2xx-no-op detection (a service call that changed zero states logs a
   warning) must survive.
6. Each phase must be independently deployable and independently revertible.

### Constraints

- Single-process deployment (one `daphne`), as ADR-0103 documents.
- The library's API surface has moved between releases: the soft import that used
  to live here tried `from homeassistant_api import Client` then
  `from homeassistant_api.client import Client`. Any adoption must pin a version.
- The alarm is a live system. The `list_entities` → `sync_entity_states` → `Entity`
  → sensors path is load-bearing for arming and triggering.
- Two claims below are **verified**; two are **not**, and are recorded as open
  questions rather than assumptions (see Risks).

## Options Considered

### Option 1: Adopt the library, phased and pinned (chosen)

**Description:** Pin `homeassistant-api==6.0.1` and migrate the transport one
function at a time, lowest-risk first, with a shape-parity test per function
before each switch. The riskiest path (`list_entities`, which feeds sensors) moves
last.

**Pros:**
- Removes ~860 lines of hand-rolled transport we currently maintain
- Typed pydantic models replace 45 hand-rolled `isinstance` / `json.loads` guards
- Upstream tracks Home Assistant API changes instead of us
- One dependency covers **both** REST and websocket, so `state_stream.py` can be
  retired too
- The dependency is already shipped, so no new supply-chain surface is introduced
- Phasing means each step is small, deployable, and revertible

**Cons:**
- Adds a hard runtime dependency on third-party code for the alarm's HA integration
- Requires a field-by-field shape audit; the `last_changed` drift is known, others
  may not be
- `trigger_service` takes service data as `**kwargs`, while our rules engine passes
  arbitrary user-authored fields
- Migration touches the path that arms and triggers the alarm

### Option 2: Stay REST-only, permanently

**Description:** Treat the hand-rolled transport as the intended design, remove the
unused dependency, and document REST as the single supported path.

**Pros:**
- Zero migration risk — the current code is battle-tested in prod
- No third-party dependency in the alarm's HA path at all
- Full control over timeouts, error mapping, and content-type validation

**Cons:**
- We keep maintaining ~860 lines of transport, including our own websocket
  protocol implementation
- We absorb every future Home Assistant API change ourselves
- Per-field type guarding stays hand-written and easy to get subtly wrong
- Rejects a maintained library that demonstrably covers our whole surface

### Option 3: Fix `api_url` and let the client activate behind the fallback

**Description:** Correct the URL so the client path starts working, keeping raw
HTTP as the fallback it was written to be. This was PR #85.

**Pros:**
- Very small diff; would have quieted the log noise immediately
- Keeps the fallback as a safety net against exceptions

**Cons:**
- **Rejected.** It silently activates a never-executed parser on the sensor path.
  `State.last_changed` is a `datetime` where REST yields an ISO string, so row
  shapes feeding the `Entity` table change with no error raised anywhere.
- The `except Exception` provides no protection, because the failure mode is the
  client *succeeding* differently
- Migrates the riskiest function first, by accident, with no audit
- Leaves two parsers for the same data indefinitely

## Decision

**Chosen Option:** Option 1 — adopt the library, phased and pinned.

**Rationale:**

- The library covers our entire surface. Verified against the installed 6.0.1:

  | Ours | Library |
  |------|---------|
  | `get_status` | `check_api_running()`, `check_api_config()` |
  | `list_entities` | `get_states()`, `get_entities()` |
  | `call_service` | `trigger_service(...) -> tuple[State, ...]` — returns changed states, exactly what requirement 5 needs |
  | `list_services`, `list_service_catalog` | `get_domains() -> dict[str, Domain]`, `get_domain(domain_id)` |
  | `list_notify_services` | derived from `get_domains()` |
  | `state_stream.py` websocket | `homeassistant_api.websocket` (`BaseWebsocketClient`, `AuthRequired`/`AuthOk`/`AuthInvalid`) |

- Option 2's only real advantage is inertia. "It works today" argues for careful
  sequencing, not for permanently hand-rolling a transport a maintained library
  provides.
- Option 3 is rejected on the specific evidence above: it is the one path that
  changes sensor-facing data shapes without raising anything.
- Phasing addresses the sole legitimate objection to Option 1. The risk is not
  the destination, it is switching the sensor path without an audit — so that
  switch goes last, behind explicit parity verification.

## Acceptance Criteria

- [ ] **AC-1**: `requirements.txt` pins `homeassistant-api==6.0.1`; a build from a
  clean checkout resolves exactly that version.
- [ ] **AC-2**: Per-call timeouts are demonstrated to reach the underlying HTTP
  request through the library — a call against an unresponsive host raises within
  the configured bound (2s status / 5s entities) rather than hanging. If this
  cannot be demonstrated, Phase 1 does not proceed.
- [ ] **AC-3**: `get_status` via the library returns a `HomeAssistantStatus` equal
  to the REST implementation's for each case: reachable, unreachable, HTTP error,
  and not-configured; and still raises `HomeAssistantNotConfigured` /
  `HomeAssistantNotReachable` at the same boundaries.
- [ ] **AC-4**: The service catalog and notify-service lists produced via
  `get_domains()` are equal to the REST implementation's output for the same HA
  instance, including the slimmed field shape the rules UI consumes.
- [ ] **AC-5**: A service call via `trigger_service` applies the
  `entity_ids`→`entity_id` remap, and a call that changes zero states still logs
  the no-op warning from PR #78, while targetless calls (`notify.*`) still do not.
- [ ] **AC-6**: A parity test asserts the library and REST paths produce
  **identical** `list_entities` rows for the same HA payload — every key
  (`entity_id`, `domain`, `state`, `name`, `device_class`, `unit_of_measurement`,
  `last_changed`, nested `zwavejs.node_id` / `zwavejs.home_id`) equal in both value
  and type, with `last_changed` normalized to the ISO string the `Entity` table
  already stores.
- [ ] **AC-7**: After each phase's deploy, prod logs show the migrated path
  succeeding with no new warnings or exceptions, and the HA mirror entity
  (`alarm_control_panel.latchpoint_alarm`) reports the alarm state unchanged
  across the container recreate.
- [ ] **AC-8**: The full backend suite passes at every phase boundary, and entity
  count in the `Entity` table after a `sync_entity_states` run is unchanged from
  the pre-migration baseline.

## Consequences

### Positive

- Removes ~860 lines of hand-rolled transport across the full migration (529 in
  `impl.py`, 332 in `state_stream.py`)
- Typed pydantic models replace 45 hand-rolled type guards
- Upstream absorbs Home Assistant API changes
- One dependency covers REST and websocket, retiring a second transport style
- Converts a currently-unused, unpinned dependency into a pinned, used one

### Negative

- Introduces a hard runtime dependency on third-party code in the alarm's HA path
- The migration touches the path that arms and triggers the alarm, so each phase
  needs prod verification rather than tests alone
- Losing the raw-HTTP path removes a fallback that, while never exercised as
  designed, is the code with the actual production track record. Whether to keep
  it per phase is an explicit decision, not a default.
- `**kwargs` service data is a sharper edge than a JSON dict for user-authored
  rule fields

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Silent field-shape drift changes `Entity` rows and thus sensor behavior (the PR #85 failure mode) | Medium | **High** | AC-6 parity test comparing library vs REST output key-by-key including types; `list_entities` migrates **last** (Phase 4); baseline entity count checked after deploy (AC-8) |
| Per-call timeout does not survive through the library, so an unresponsive HA hangs a scheduler tick | Medium | High | **Unverified today.** AC-2 gates Phase 1 — if timeouts cannot be demonstrated, the migration stops before any function moves |
| Library API moves between releases (the old two-step soft import is evidence it already has) | Medium | Medium | Pin `==6.0.1` (Phase 0); treat upgrades as their own reviewed change |
| `trigger_service`'s `**kwargs` rejects a user-authored service field that the JSON body accepted | Low | Medium | Validate keys are Python identifiers before the call and fall back or error explicitly rather than silently dropping fields |
| Library exceptions bypass our domain exception boundaries | Medium | Medium | Explicit mapping to `HomeAssistantNotConfigured` / `HomeAssistantNotReachable`, asserted by AC-3 |
| A dead client path is reintroduced and hidden by a broad `except`, repeating the whole class of bug this ADR came from | Medium | Medium | No `except Exception: pass` around a transport call; every phase leaves exactly **one** path for its function, never a preferred-plus-fallback pair |

## Implementation Plan

- [ ] **Phase 0**: Pin `homeassistant-api==6.0.1` in `requirements.txt`. Verify
  `AC-2` (per-call timeouts) before writing any migration code — this phase can
  legitimately end the ADR if timeouts cannot be made to work. (AC-1, AC-2)
- [ ] **Phase 1**: Migrate `get_status` / `ensure_available`. Lowest risk: boolean
  reachability, no row shapes. Deploy and verify. (AC-3, AC-7)
- [ ] **Phase 2**: Migrate `list_services`, `list_service_catalog`,
  `list_notify_services` via `get_domains()`. Read-only and UI-facing. (AC-4, AC-7)
- [ ] **Phase 3**: Migrate `call_service` to `trigger_service`, preserving the
  target-key remap and the changed-states no-op warning. (AC-5, AC-7)
- [ ] **Phase 4**: Migrate `list_entities` — **the riskiest step**. Full field
  parity audit first, `last_changed` normalized to the ISO string. Verify entity
  count after deploy. (AC-6, AC-7, AC-8)
- [ ] **Phase 5**: Optionally retire `state_stream.py` in favour of
  `homeassistant_api.websocket`. Separate and deferrable — the hand-rolled
  websocket works and has a production track record.

Each phase: shape audit → tests → deploy → verify prod logs and the HA mirror.

## Related ADRs

- [ADR-0103](./0103-idle-scheduler-and-ingest-quiet-down.md) - The log-noise work
  that surfaced this. Its `_settings_snapshot` caching precedent and the
  single-process deployment assumption both apply here.
- [ADR-0079](./0079-ui-config-with-encrypted-credentials.md) - HA connection
  settings (`base_url`, token) are DB-backed per profile with the token encrypted at
  rest, which is what the transport reads.

## References

- Library: [HomeAssistant-API](https://github.com/HomeAssistant-API/HomeAssistantAPI),
  installed version 6.0.1
- Home Assistant [REST API](https://developers.home-assistant.io/docs/api/rest/) and
  [WebSocket API](https://developers.home-assistant.io/docs/api/websocket)
- PR #78 — removed the dead `call_service` client branch; added 2xx-no-op detection
- PR #85 — **closed unmerged**; fixed `api_url` and was rejected for activating the
  never-executed parser on the sensor path
- PR #86 — removed the remaining two dead client branches, leaving REST as the
  single transport
