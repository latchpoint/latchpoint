# Frigate MQTT → Rules Conditions (Implementation Phases)

Goal: use Frigate MQTT “person” events as **rule conditions** so you can express policies like:
- “If `armed_away` AND a person is detected in `backyard` zone at ≥ 90% confidence, then trigger.”
- “If `armed_home` AND person detected on `porch` camera at ≥ 80%, then notify only.”

This plan assumes:
- MQTT transport is configured/enabled (Frigate condition support depends on it).
- Rules engine remains “thin + deterministic” (no direct network calls during evaluation).
- Settings live in the active `AlarmSettingsProfile` and secrets are encrypted at rest.

## Phase 0 — Decide MQTT contract + data model (blocking)
**Deliverables**
- Confirm which Frigate MQTT topic(s) we subscribe to (events vs detections).
- Define the minimal normalized detection schema we store for rule evaluation.
- Define “availability” semantics for `on_unavailable` (“ignore Frigate if down”).

**Recommended normalized record**
- `provider="frigate"`, `label="person"`, `camera`, `zones[]`, `confidence_pct`, `observed_at`, `event_id?`, `raw?`

**Acceptance**
- We can write unit tests for parsing + confidence normalization with fixture payloads.

## Phase 1 — Backend: integration skeleton + ingestion + status (no rules yet)
**Backend work**
- Create `backend/integrations_frigate/` app:
  - MQTT subscription wiring via existing MQTT transport.
  - Parsing of Frigate payloads into normalized detection records.
  - Confidence normalization to `confidence_pct ∈ [0,100]`.
- Add DB storage + pruning:
  - New model/table for detections with indexes on `observed_at`, `camera`, `label`.
  - Management command or scheduled pruning path (simple “delete older than retention”).
- Add status endpoint (admin-only):
  - MQTT connected?
  - last detection received time
  - ingestion error counters (in-memory or persisted)

**Settings (active profile)**
- `frigate_enabled` (bool)
- `frigate_mqtt_topic_prefix` or explicit topics (advanced)
- `frigate_retention_seconds` (e.g., 3600)
- `frigate_availability_grace_seconds` (e.g., “consider down if no events for 120s”)

**Frontend work**
- Settings tab/page: “Frigate”
  - enable toggle
  - retention + availability settings (keep MQTT topics behind an “Advanced” accordion)
  - status display (connected / last event)

**Acceptance**
- Turning on Frigate shows “receiving events” within the UI.
- Detections appear in DB and are pruned on schedule/command.

## Phase 2 — Backend: repository boundary + rule condition op (read-only evaluation)
**Backend work**
- Add a repository method for detections (align with ADR 0009):
  - `find_recent_detections(provider, label, cameras, since, zones?) -> list[Detection]`
  - `frigate_is_available(now) -> bool`
- Extend rules conditions to support a new op, e.g. `frigate_person_detected`:
  - Params:
    - `cameras: string[]` (required)
    - `zones: string[]` (optional)
    - `within_seconds: int` (required)
    - `min_confidence_pct: number` (required)
    - `aggregation: "latest" | "max" | "percentile"` (default `"max"`)
    - `percentile: int` (required if aggregation is percentile)
    - `on_unavailable: "treat_as_match" | "treat_as_no_match"` (default `"treat_as_no_match"`)
  - Implement `eval_condition_explain` trace output for debugging and RulesTestPage.
- Update rule evaluation plumbing to pass the extra context needed:
  - `now`
  - repository access (or a precomputed “facts” object derived from repos)

**Acceptance**
- Rules simulation (`/api/alarm/rules/simulate/`) can evaluate the Frigate condition deterministically.
- Explain output clearly shows which detections were considered and the computed aggregated confidence.

## Phase 3 — Frontend: rule builder support for Frigate condition
**Frontend work**
- Extend the rules editor UI to allow adding a “Person detected (Frigate)” condition:
  - camera multi-select
  - zone multi-select (optional)
  - window seconds
  - threshold (percent)
  - aggregation mode (max/latest/percentile + percentile selector)
  - “If Frigate is down” toggle that maps to `on_unavailable`
- Add a small “Frigate schema helper” endpoint if needed:
  - list known cameras/zones based on recent detections (or configured list)

**Backend support (if needed)**
- `GET /api/alarm/frigate/options/`:
  - `cameras: string[]`
  - `zones_by_camera: { [camera]: string[] }`

**Acceptance**
- A user can author a rule matching: person in backyard zone >= 90% in last 10s.
- Rules test page can simulate and show explain traces.

## Phase 4 — End-to-end actions + alarm-state scoping
**Backend**
- Ensure rules can scope by alarm state (whichever pattern the app uses today):
  - Implemented via a dedicated condition op: `alarm_state_in`.
- Ensure actions include:
  - trigger alarm (transition to triggered) OR notify only
- Confirm that Frigate-driven rules can be the *primary* trigger (MQTT event arrives → evaluation loop sees matching condition within window).

**Frontend**
- Add examples/presets:
  - “Armed away + backyard person >= 90% → trigger”
  - “Armed home + porch person >= 80% → notify”

**Acceptance**
- With Frigate enabled and armed, a person event can cause trigger/notify according to the rule.

## Example rules
**Armed away + backyard person >= 90% → trigger**
```json
{
  "when": {
    "op": "all",
    "children": [
      { "op": "alarm_state_in", "states": ["armed_away"] },
      {
        "op": "frigate_person_detected",
        "cameras": ["backyard"],
        "zones": ["yard"],
        "within_seconds": 10,
        "min_confidence_pct": 90,
        "aggregation": "max",
        "on_unavailable": "treat_as_no_match"
      }
    ]
  },
  "then": [{ "type": "alarm_trigger" }]
}
```

## Phase 5 — Hardening: performance, correctness, and ops
**Backend**
- Add indexes tuned for queries by `camera`, `label`, `observed_at`.
- Add rate limiting / backpressure for very chatty MQTT topics.
- Add structured logging and counters for parsing failures and dropped events.
- Add a clear admin “Frigate status” page and API health integration.

**Testing**
- Unit tests:
  - payload parsing + confidence normalization (0–1 vs 0–100)
  - zone filtering
  - aggregation calculations (latest/max/percentile)
  - `on_unavailable` behaviors
- Optional opt-in integration tests behind `ALLOW_FRIGATE_IN_TESTS=true`.

**Acceptance**
- Rules evaluation remains fast under bursty events.
- Clear operational diagnostics when Frigate/MQTT is misconfigured.

## Open questions (to close before Phase 1)
- Which exact MQTT topics/payload format are we targeting (Frigate version/config dependent)?
- Do we need per-camera confidence thresholds, or is per-rule enough?
- How do we define availability: MQTT connected, or “received event recently”, or both?
- Should “zones” matching be “any overlap” (recommended) or “must include all”?
