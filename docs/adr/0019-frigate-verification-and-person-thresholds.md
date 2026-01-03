# ADR 0019: Frigate MQTT Person Events as Rules Conditions (Confidence Thresholds)

## Status
**Implemented**

## Context
We want to integrate Frigate (NVR + object detection) so the alarm system can:
- Use Frigate **person detection** as an input to the **rules engine**, e.g.:
  - “If a person is detected in the backyard camera at ≥ 90% confidence, then trigger.”
  - “If armed_home and person detected in porch zone, then notify only.”
- Allow configuration of **which alarm states** should evaluate/allow these rules (similar to existing alarm rules patterns).
- Support camera + zone selection (Frigate camera and Frigate zone).
- Use the confidence score provided by Frigate MQTT events (as a percentage), optionally with percentile-based aggregation over a time window.
- Control behavior when Frigate is unavailable (“ignore Frigate if down” vs “require Frigate”).

This must align with the existing architecture:
- Core alarm logic depends on gateways in `backend/alarm/gateways/*`, not integration implementations directly.
- Integration settings live in the active `AlarmSettingsProfile` and secrets are encrypted at rest.
- Tests must not call external systems by default.

## Decision
### 1) Use Frigate via MQTT events (MQTT transport required)
- Frigate integration consumes **MQTT events** and stores normalized detections for rule evaluation.
- MQTT is a hard dependency for this integration:
  - The integration subscribes using the existing MQTT transport (`backend/transports_mqtt/`).
  - If MQTT is disabled/not configured, Frigate conditions are unavailable.
 - Ingest can optionally **run rules automatically** (debounced) so Frigate-driven rules fire in near real-time.

### 2) Represent Frigate detections as a rule queryable dataset
To avoid network calls during rule evaluation, ingest MQTT events and persist a small, queryable record of detections.

**Normalized detection record (conceptual)**
- `provider`: `frigate`
- `label`: e.g. `person`
- `camera`: Frigate camera name (string)
- `zones`: list of Frigate zone names (strings)
- `confidence_pct`: float in `[0, 100]`
- `observed_at`: timestamp
- `event_id`: optional (if Frigate provides one)
- `raw`: JSON payload (optional, for debugging/audit)

Retention should be short (e.g. 1–24 hours) and configurable; older events are pruned.

### 3) Rule condition: “person detected” with confidence threshold
Add a rules-engine condition that queries the recent detections dataset.

Example condition parameters:
- `camera`: one or many cameras
- `zones`: optional (if set, require intersection with detection zones)
- `label`: default `person`
- `within_seconds`: time window to consider (e.g., last 10 seconds)
- `min_confidence_pct`: e.g. `90`
- `aggregation`: `latest | max | percentile`
  - `percentile`: optional (e.g., `p=90`) computed over candidates in the window
- `on_unavailable`: behavior when Frigate/MQTT is unavailable:
  - `treat_as_match` (“ignore Frigate if down”)
  - `treat_as_no_match` (“require Frigate”)
  - (Future) `error` (fail evaluation; primarily for debugging)

### 3b) Alarm state scoping as a first-class condition
Rules commonly need to scope by alarm state (e.g. only apply when `armed_away`). We support this via a condition like:
- `{"op": "alarm_state_in", "states": ["armed_away", "armed_home"]}`

### 4) Percentile aggregation (optional, deterministic)
If the condition uses `aggregation=percentile`, compute a percentile over the candidate confidences using the “nearest-rank” method:
- Let `scores` be the list of confidences, sorted ascending, length `n`.
- Let `p` be a configured percentile in `(0, 100]` (e.g., `90`).
- Rank `k = ceil((p / 100) * n)` (1-based).
- Percentile value is `scores[k - 1]`.

Decision rule:
- If aggregated value `>= min_confidence_pct` then the condition matches.
- If there are **no candidates**, the condition does not match (unless overridden by `on_unavailable=treat_as_match` due to provider unavailability).

Rationale:
- Percentiles reduce sensitivity to single-event spikes and encourage “consistent confidence”.
- Nearest-rank is simple, predictable, and easy to test.

### 5) Confidence normalization
Frigate MQTT payloads may report confidence as a percentage or as a 0–1 float depending on topic/version/config.
We normalize to `confidence_pct` in `[0, 100]`:
- If `0 <= c <= 1`, treat as fraction and multiply by 100.
- If `1 < c <= 100`, treat as percent.
- Otherwise clamp and log a warning.

### 6) Alarm-state scoping
Rules that reference Frigate conditions should be able to specify which alarm states they apply to (or use existing rule “state” gating if present).
This keeps “armed_away only” vs “armed_home/night” behavior explicit and user-configurable.

### 7) Provider boundary (gateways/repositories)
- Core rule evaluation should query through a repository boundary (per ADR 0009):
  - e.g., a `DetectionsRepository` method like `find_detections(provider, label, cameras, since)`.
- The Frigate integration is responsible for ingesting MQTT events and writing detection records.
- Status (up/down) is derived from MQTT connection state and recent event timestamps, exposed via an admin status endpoint.

## Alternatives Considered
- **HTTP polling Frigate API**: simpler to reason about but adds latency and network calls to rule evaluation.
- **MQTT-only vs hybrid MQTT+HTTP**: hybrid can add media links/snapshots, but MQTT-only meets the “conditions” requirement with less surface area.
- **Always trigger, use Frigate only for notifications**: reduces missed alarms but doesn’t satisfy “only trigger if person >= 90%” use cases.
- **Integrate via Home Assistant entities only**: HA may not expose Frigate zones/event confidence uniformly; Frigate MQTT is the most direct signal.

## Consequences
- Enables powerful “trigger only when person is detected” rules, reducing false alarms for motion-based sensors.
- Makes MQTT a required dependency for Frigate-based automations; deployments without MQTT cannot use these conditions.
- Adds configuration and UX complexity (camera/zone selection, windows, thresholds, unavailability policy).
- Requires careful defaults for `on_unavailable`:
  - `treat_as_no_match` is safer for “only trigger if person” semantics.
  - `treat_as_match` is safer for “always trigger, Frigate is optional” semantics.
- Requires data retention/pruning for ingested detections.

## Todos
- Implementation plan: `docs/planning/frigate-rules-integration-phases.md`.
- (Done) Define Frigate MQTT settings and defaults in the settings registry (enable flag, topics, retention, and “availability” thresholds).
- (Done) Add `backend/integrations_frigate/` with MQTT ingest, detection persistence, pruning, and status/settings endpoints.
- (Done) Extend the rules engine with `frigate_person_detected` and `alarm_state_in` conditions, including percentile aggregation and availability behavior.
- (Done) Add frontend settings + rules builder UI for Frigate camera/zone selection and confidence thresholds.
- (Done) Add unit tests for payload parsing/normalization, percentile aggregation, and condition evaluation.
- Gate any real MQTT/Frigate integration tests behind `ALLOW_FRIGATE_IN_TESTS=true`.
