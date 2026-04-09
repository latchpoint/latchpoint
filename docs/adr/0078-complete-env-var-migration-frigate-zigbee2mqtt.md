# ADR 0078: Complete Env-Var Migration for Frigate and Zigbee2MQTT

**Status:** Implemented
**Date:** 2026-04-09
**Author:** Leonardo Merza

## Context

### Background

[ADR 0075](0075-env-var-credentials-remove-encryption.md) moved all integration credentials and connection parameters to environment variables, eliminating the encryption layer. However, it explicitly left Frigate and Zigbee2MQTT in a **hybrid state**: the `enabled` flag, MQTT topic, and retention come from env vars, but several operational fields remain DB-backed and editable through the UI via `AlarmSettingsEntry`.

The app is pre-release. There are no external deployments to migrate.

### Current State

**Frigate** — DB-backed fields (stored in `AlarmSettingsEntry` key `"frigate"`):
- `known_cameras` (list of strings) — auto-discovered camera names
- `known_zones_by_camera` (dict: camera → zones list) — auto-discovered zone data
- `enabled`, `events_topic`, `retention_seconds` — env vars override these at runtime, but DB values still exist

**Zigbee2MQTT** — DB-backed fields (stored in `AlarmSettingsEntry` key `"zigbee2mqtt"`):
- `allowlist` / `denylist` (lists) — device filtering
- `run_rules_on_event` (bool), `run_rules_debounce_seconds` (int), `run_rules_max_per_minute` (int), `run_rules_kinds` (list) — rules-triggering config
- `enabled`, `base_topic` — env vars override these at runtime, but DB values still exist

**Additional inconsistencies:**
- Frigate and Zigbee2MQTT have working `PATCH` endpoints and editable frontend forms, unlike HA/MQTT/ZWaveJS which correctly return 405
- The Frigate frontend form shows `run_rules_*` fields that the backend serializer silently ignores — dead config in the UI
- Z-Wave JS frontend shows editable input fields despite having no save endpoint

### Requirements

- All integration settings must come from environment variables — no DB persistence for config
- Settings pages must be read-only status displays
- No hybrid state — a single source of truth (env vars) for all integration config

### Constraints

- Pre-release: breaking changes are acceptable, no migration path needed for external users
- `known_cameras` and `known_zones_by_camera` are discovered from Frigate MQTT events, not operator-configured
- Comma-separated env var lists are sufficient for allowlist/denylist (device IDs are simple strings)

---

## Options Considered

### Option 1: All Settings to Env Vars, Auto-Discover Camera Data

**Description:** Move all Zigbee2MQTT operational fields to env vars. Remove Frigate's `known_cameras` and `known_zones_by_camera` from settings entirely — they're runtime-discovered data, not configuration. Remove all PATCH endpoints and make frontend read-only.

**Pros:**
- Single source of truth for all config (env vars)
- Frigate camera/zone data is genuinely discovered, not configured — removing it from settings is semantically correct
- Consistent with HA/MQTT/ZWaveJS pattern established in ADR 0075
- No DB writes for integration config at all

**Cons:**
- Operators must redeploy to change allowlist/denylist or rules config
- Comma-separated lists in env vars are less ergonomic than a UI form for allowlists

### Option 2: Move to Env Vars, Including Camera Data

**Description:** Same as Option 1 but also add `FRIGATE_KNOWN_CAMERAS` and `FRIGATE_KNOWN_ZONES` env vars so operators can pre-declare cameras.

**Pros:**
- Operators can restrict which cameras are processed before any events arrive

**Cons:**
- `known_cameras` is discovered data, not config — requiring operators to list cameras duplicates what Frigate already knows
- `FRIGATE_KNOWN_ZONES` would need JSON encoding in an env var (awkward)
- Adds env vars for data that auto-populates naturally

### Option 3: Keep Frigate/Zigbee2MQTT Hybrid (Status Quo)

**Description:** Leave Frigate and Zigbee2MQTT with DB-backed settings and editable UI. Only HA/MQTT/ZWaveJS are env-only.

**Pros:**
- No work required
- UI editing is more convenient for list-type config

**Cons:**
- Inconsistent architecture: some integrations are env-only, others are hybrid
- Two sources of truth: env vars override some DB fields at runtime, causing confusion
- Frigate frontend shows dead `run_rules_*` fields
- PATCH endpoints exist for Frigate/Zigbee2MQTT but not HA/MQTT/ZWaveJS

---

## Decision

**Chosen Option:** Option 1 — All settings to env vars, auto-discover camera data

**Rationale:** Consistency is more valuable than UI convenience for a self-hosted appliance configured at deployment time. The hybrid state creates confusion (env vars silently overriding DB values, editable forms that suggest persistence when env wins at runtime). Frigate camera/zone data is genuinely discovered — it was never configuration. Pre-release status means no migration burden.

### New Environment Variables

```bash
# Zigbee2MQTT (additions to existing vars from ADR 0075)
ZIGBEE2MQTT_ALLOWLIST=                       # comma-separated device IDs
ZIGBEE2MQTT_DENYLIST=                        # comma-separated device IDs
ZIGBEE2MQTT_RUN_RULES_ON_EVENT=false
ZIGBEE2MQTT_RUN_RULES_DEBOUNCE_SECONDS=5
ZIGBEE2MQTT_RUN_RULES_MAX_PER_MINUTE=60
ZIGBEE2MQTT_RUN_RULES_KINDS=                 # comma-separated: state_change,action
```

No new Frigate env vars — `FRIGATE_ENABLED`, `FRIGATE_EVENTS_TOPIC`, and `FRIGATE_RETENTION_SECONDS` from ADR 0075 are sufficient. Camera/zone discovery is runtime-only.

### Backend Changes

| Component | Action |
|-----------|--------|
| `alarm/env_config.py` | Add `get_zigbee2mqtt_config()` with full field set (replace `get_zigbee2mqtt_env_overrides()`). Update `get_frigate_env_overrides()` → `get_frigate_config()` (no overrides, this IS the config). |
| `integrations_frigate/views.py` | Replace `patch()` with 405 `MethodNotAllowed`, same pattern as HA/MQTT/ZWaveJS. `get()` returns env config only. |
| `integrations_zigbee2mqtt/views.py` | Replace `patch()` with 405 `MethodNotAllowed`. `get()` returns env config only. |
| `integrations_frigate/runtime.py` | Remove DB read/merge logic. `get_settings()` calls `get_frigate_config()` directly. Camera/zone discovery stays in-memory. |
| `integrations_zigbee2mqtt/runtime.py` | Remove DB read/merge logic. `get_settings()` calls `get_zigbee2mqtt_config()` directly. |
| `alarm/settings_registry.py` | Remove `frigate` and `zigbee2mqtt` entries from `ALARM_PROFILE_SETTINGS`. |
| Serializers | Remove `FrigateSettingsUpdateSerializer` and Zigbee2MQTT update serializer. Keep read-only response serializers. |

### Frontend Changes

| Component | Action |
|-----------|--------|
| `FrigateSettingsCard.tsx` | Make read-only display (like `HomeAssistantConnectionCard`). Remove save/reset handlers. Remove dead `run_rules_*` form fields. |
| `Zigbee2mqtSettingsCard.tsx` | Make read-only display. Remove save/reset handlers. |
| `ZwavejsSettingsCard.tsx` | Fix: make form inputs disabled/read-only (currently editable but no save endpoint). |
| `useFrigateSettingsModel.ts` | Remove `save()`, `useUpdateFrigateSettingsMutation()`. Read-only fetch only. |
| `useZigbee2mqttSettingsModel.ts` | Remove `save()`, update mutation. Read-only fetch only. |
| `frigate.ts` (API service) | Remove PATCH call. |
| `zigbee2mqtt.ts` (API service) | Remove PATCH call. |

### Frigate Camera/Zone Discovery

`known_cameras` and `known_zones_by_camera` become purely runtime state:
- Built in-memory from incoming Frigate MQTT events
- Not persisted to DB or configured via env
- Available via GET endpoint for the UI to display (read-only)
- Reset on container restart (repopulates as events arrive)

---

## Consequences

### Positive
- **Single source of truth**: all integration config lives in env vars, no DB/env hybrid confusion
- **Consistent architecture**: all five integrations (HA, MQTT, ZWaveJS, Zigbee2MQTT, Frigate) follow the same pattern
- **Simpler backend**: remove PATCH endpoints, update serializers, DB merge logic, and settings registry entries for both integrations
- **Simpler frontend**: settings pages are uniform read-only displays across all integrations
- **Correct semantics**: Frigate camera/zone data was always discovered, not configured — treating it as settings was wrong
- **Removes dead config**: Frigate `run_rules_*` fields that were silently ignored are gone

### Negative
- **Less convenient list editing**: changing Zigbee2MQTT allowlist requires editing env and restarting, not clicking in the UI. Acceptable for a deployment-time config.
- **Camera data is ephemeral**: `known_cameras` resets on restart. Mitigated by rapid repopulation from Frigate events.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Operator confusion about where to configure | Low | Low | `.env.example` is well-documented; settings pages show current values read-only |
| Allowlist too large for env var | Low | Low | Env vars support very long values; unlikely to have hundreds of Zigbee devices in a filter |
| Camera data lost on restart | Medium | Low | Repopulates within seconds as Frigate publishes events continuously |

---

## Implementation Plan

- [ ] Phase 1: Backend — expand `env_config.py` with full Zigbee2MQTT and Frigate config functions
- [ ] Phase 2: Backend — update `runtime.py` for both integrations to read from env only, remove DB merge logic
- [ ] Phase 3: Backend — replace PATCH endpoints with 405 for both integrations
- [ ] Phase 4: Backend — remove `frigate` and `zigbee2mqtt` from `settings_registry.py`, remove update serializers
- [ ] Phase 5: Backend — make Frigate camera/zone data runtime-only (in-memory, not persisted)
- [ ] Phase 6: Frontend — make Frigate and Zigbee2MQTT settings pages read-only displays
- [ ] Phase 7: Frontend — fix Z-Wave JS settings page inputs to be disabled/read-only
- [ ] Phase 8: Update `.env.example` with new Zigbee2MQTT env vars
- [ ] Phase 9: Add/update tests for 405 responses and env-only config

## Related ADRs

- [ADR 0075](0075-env-var-credentials-remove-encryption.md) — predecessor; moved credentials to env vars but left Frigate/Zigbee2MQTT hybrid. This ADR completes that migration.
- [ADR 0018](0018-zigbee2mqtt-integration.md) — original Zigbee2MQTT integration design
- [ADR 0019](0019-frigate-verification-and-person-thresholds.md) — Frigate integration design
- [ADR 0051](0051-standardize-integration-settings-ui-cards.md) — standardized settings UI cards (now all read-only)

## References

- `backend/alarm/env_config.py` — central env var reading
- `backend/alarm/settings_registry.py` — DB-backed settings to remove
- `backend/integrations_frigate/views.py` — Frigate PATCH endpoint to remove
- `backend/integrations_zigbee2mqtt/views.py` — Zigbee2MQTT PATCH endpoint to remove
