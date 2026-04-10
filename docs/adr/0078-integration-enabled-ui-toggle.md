# ADR 0078: Move Integration Enabled Flags from Environment Variables to UI Toggle

## Status
**Proposed**

## Context

ADR 0075 moved all integration configuration — including `enabled` flags — to environment variables. While this simplified credential management, it made enabling/disabling integrations require a container restart and `.env` file edit, which is unnecessarily heavy for an operational toggle.

### Problems with env-var-based enabling

1. **Operator friction**: Toggling an integration on/off requires editing `.env` and restarting the container, even though the UI already has toggle switches (just disabled).

2. **Z-Wave JS UI confusion**: The Z-Wave JS settings card has editable Input fields for WebSocket URL, connect timeout, reconnect min/max — but PATCH returns 405. The fields accept input that can never be saved.

3. **Frigate/Zigbee2MQTT env overrides always win**: `FRIGATE_ENABLED`, `FRIGATE_EVENTS_TOPIC`, `FRIGATE_RETENTION_SECONDS`, `ZIGBEE2MQTT_ENABLED`, `ZIGBEE2MQTT_BASE_TOPIC` override DB values on every read. UI edits to these fields are silently discarded.

4. **Notification providers re-stamped on restart**: `ensure_env_providers_exist()` re-enables or disables providers based on `*_ENABLED` env vars on every startup, overriding any UI toggle changes.

### Guiding principle

**Env vars are for infrastructure-level connection config (URLs, credentials, ports, timeouts). Enabling/disabling is an operational decision managed via the UI.**

Anything set by env var is shown read-only in the UI (raw passwords hidden). Anything managed by UI toggle is stored in the DB and never overridden by env vars.

---

## Decision

### 1. Remove `*_ENABLED` env vars for all integrations and notification providers

Remove from `env_config.py`:
- `HA_ENABLED`, `MQTT_ENABLED`, `ZWAVEJS_ENABLED`
- `ZIGBEE2MQTT_ENABLED`, `ZIGBEE2MQTT_BASE_TOPIC`
- `FRIGATE_ENABLED`, `FRIGATE_EVENTS_TOPIC`, `FRIGATE_RETENTION_SECONDS`
- `PUSHBULLET_ENABLED`, `DISCORD_ENABLED`, `SLACK_ENABLED`, `WEBHOOK_ENABLED`, `HA_NOTIFY_ENABLED`

### 2. Store `enabled` in DB via `AlarmSettingsEntry` for core integrations

Add new setting definitions to `settings_registry.py`:
- `home_assistant`: `{"enabled": false}`
- `mqtt`: `{"enabled": false}`
- `zwavejs`: `{"enabled": false}`

Zigbee2MQTT and Frigate already have `enabled` in their existing DB settings blobs.

### 3. Move Frigate/Zigbee2MQTT operational fields to DB-only

Remove `get_frigate_env_overrides()` and `get_zigbee2mqtt_env_overrides()` entirely. Their runtime `get_settings()` functions read exclusively from DB — no more env override merging.

`base_topic`, `events_topic`, `retention_seconds` become fully DB-backed and UI-editable.

### 4. Make PATCH endpoints functional for HA, MQTT, ZWaveJS

Convert PATCH from 405 to accepting `{"enabled": bool}`. Connection config (URLs, creds) remains env-var-only and read-only in the response.

### 5. Notification provider `is_enabled` managed by UI only

- `ensure_env_providers_exist()` creates provider rows when credentials are configured (non-empty), but sets `is_enabled=False` on creation. It never overrides an existing row's `is_enabled`.
- Rename `is_enabled_from_env()` to `is_configured_from_env()` — checks for non-empty credentials, not an `*_ENABLED` flag.
- `ProviderDetailView.patch()` accepts `{"is_enabled": bool}` instead of returning 405.
- Frontend shows a toggle per provider.

### 6. Z-Wave JS connection fields become read-only in UI

Replace editable Input fields with a read-only grid (matching MQTT/HA pattern). Description changes to "Connection settings are configured via environment variables."

### 7. Signal-based dynamic enable/disable for HA, MQTT, ZWaveJS

HA, MQTT, and ZWaveJS `apps.py` register `settings_profile_changed` signal handlers that re-apply the `enabled` state at runtime when toggled via UI.

---

## Consequences

### Positive
- Admins can enable/disable any integration from the UI without restart
- Clear separation: env vars = infrastructure config, DB = operational state
- No more env overrides silently discarding UI changes
- Z-Wave JS UI no longer has confusing editable-but-unsaveable fields

### Negative
- Existing deployments with `*_ENABLED=true` will find integrations disabled after upgrade (must re-enable via UI)
- HA/MQTT/ZWaveJS apps need signal handlers for dynamic enable/disable (small complexity increase)

### Migration
- Breaking change: all `*_ENABLED` env vars are removed
- First startup after upgrade: all integrations default to disabled
- Admin must enable desired integrations via UI toggle
- Credentials/URLs remain in env vars unchanged

---

## References

- [ADR 0075: Move Integration Credentials to Environment Variables and Remove Encryption](0075-env-var-credentials-remove-encryption.md) — **Partially reversed by this ADR** (enabled flags move back to DB; credentials stay in env)
