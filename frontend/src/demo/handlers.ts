/**
 * MSW request handlers for demo mode.
 *
 * Responses use snake_case keys matching the Django backend; the ApiClient
 * (frontend/src/services/api.ts:206) auto-converts to camelCase before
 * reaching React. All responses are wrapped in the ADR-0025 success envelope
 * `{data, meta?}` which the client unwraps at api.ts:209.
 *
 * MVP scope (per ADR-0089): every boot-critical endpoint returns realistic
 * data; CRUD lists are seeded; mutations modify in-memory stores; everything
 * else falls through to a catchall that returns `{data: []}` for GET (so
 * list-shaped consumers don't crash on `.map`/`.length`) and `{data: null}`
 * for other methods. Expand specificity as needed.
 */

import { http, HttpResponse, delay } from 'msw'
import { stores, nextDemoId } from './stores'
import { demoUsers, demoSettingsRegistry } from './fixtures'

const ok = <T,>(data: T, meta?: Record<string, unknown>) =>
  HttpResponse.json(meta ? { data, meta } : { data })

const ADMIN = demoUsers[0]

// Module-level auth flag so logout actually surfaces the login screen.
// Default `true` matches ADR-0089 §7's auto-auth landing.
let authenticated = true

export const handlers = [
  // ── Auth ────────────────────────────────────────────────────────────────
  // The CSRF cookie is primed once at startup in `initDemoMode()` (page
  // context). Handlers run in the Service Worker context where `document`
  // is undefined, so we must not write the cookie here.
  http.get('/api/auth/csrf/', () => ok(null)),

  http.post('/api/auth/login/', async () => {
    await delay(200)
    authenticated = true
    return ok({
      user: ADMIN,
      access_token: 'demo-access-token',
      refresh_token: 'demo-refresh-token',
      requires_2fa: false,
    })
  }),

  http.post('/api/auth/logout/', () => {
    authenticated = false
    return ok(null)
  }),
  http.post('/api/auth/2fa/verify/', () => ok({ verified: true })),
  http.post('/api/auth/validate-code/', () => ok({ valid: true, user: ADMIN })),

  // ── Users ───────────────────────────────────────────────────────────────
  // Returns 401 when logged-out so `useAuth` flips `isAuthenticated` false and
  // ProtectedRoute redirects to `/login`. Without this, query invalidation
  // after logout silently re-authenticates and the visitor stays on `/`.
  http.get('/api/users/me/', () =>
    authenticated
      ? ok(ADMIN)
      : HttpResponse.json({ detail: 'Not authenticated' }, { status: 401 }),
  ),
  http.get('/api/users/', () => ok(demoUsers, { total: demoUsers.length })),

  // ── Onboarding / setup gate ─────────────────────────────────────────────
  http.get('/api/onboarding/', () => ok({ onboarding_required: false })),
  http.get('/api/onboarding/setup-status/', () =>
    ok({
      onboarding_required: false,
      setup_required: false,
      mqtt_configured: true,
      zwavejs_configured: true,
      ha_configured: true,
    }),
  ),

  // ── System ──────────────────────────────────────────────────────────────
  // Shape mirrors `ServerTime` from `frontend/src/services/system.ts`
  // (snake_case here → camelCase after ApiClient.transformKeysDeep).
  http.get('/api/system/time/', () => {
    const now = new Date()
    return ok({
      timestamp: now.toISOString(),
      timezone: 'UTC',
      epoch_ms: now.getTime(),
      formatted: now.toISOString().replace('T', ' ').replace(/\.\d+Z$/, ' UTC'),
    })
  }),
  http.get('/api/system-config/', () => ok([])),
  // The demo doesn't seed system-config rows (the GET above returns []), so a
  // visitor saving from SystemSettingsCard hits this PATCH with an unknown key.
  // Synthesize a `SystemConfigRow` (snake-case here → camelCase via
  // ApiClient.transformKeysDeep) so `useUpdateSystemConfig.onSuccess` sees a
  // row with `key`/`value` instead of crashing on `null`.
  http.patch('/api/system-config/:key/', async ({ params, request }) => {
    const key = String(params.key)
    const body = (await request.json().catch(() => ({}))) as {
      value?: unknown
      description?: string
    }
    const now = new Date().toISOString()
    return ok({
      key,
      name: key,
      value_type: 'string',
      value: body.value ?? null,
      description: body.description ?? '',
      modified_by_id: null,
      created_at: now,
      updated_at: now,
    })
  }),

  // ── Alarm core ──────────────────────────────────────────────────────────
  // Shapes mirror `AlarmStateSnapshot` and `ArmRequest` from
  // `frontend/src/types/alarm.ts`. The body arrives snake_case because
  // ApiClient transforms outgoing request bodies (api.ts:135) before MSW
  // intercepts them — so `targetState` becomes `target_state` on the wire.
  http.get('/api/alarm/state/', () => ok(stores.alarmState)),
  http.post('/api/alarm/arm/', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as { target_state?: string }
    const target = body.target_state ?? 'armed_away'
    stores.alarmState = {
      ...stores.alarmState,
      previous_state: stores.alarmState.current_state,
      current_state: target,
      target_armed_state: target,
      entered_at: new Date().toISOString(),
      last_transition_reason: 'user_arm',
    }
    return ok(stores.alarmState)
  }),
  http.post('/api/alarm/disarm/', () => {
    stores.alarmState = {
      ...stores.alarmState,
      previous_state: stores.alarmState.current_state,
      current_state: 'disarmed',
      target_armed_state: null,
      entered_at: new Date().toISOString(),
      last_transition_reason: 'user_disarm',
    }
    return ok(stores.alarmState)
  }),
  http.post('/api/alarm/cancel-arming/', () => {
    stores.alarmState = {
      ...stores.alarmState,
      previous_state: stores.alarmState.current_state,
      current_state: 'disarmed',
      target_armed_state: null,
      entered_at: new Date().toISOString(),
      last_transition_reason: 'user_cancel_arming',
    }
    return ok(stores.alarmState)
  }),
  http.post('/api/alarm/trigger/', () => {
    stores.alarmState = {
      ...stores.alarmState,
      previous_state: stores.alarmState.current_state,
      current_state: 'triggered',
      entered_at: new Date().toISOString(),
      last_transition_reason: 'manual_trigger',
    }
    return ok(stores.alarmState)
  }),

  http.get('/api/alarm/settings/', () => ok(stores.alarmSettings)),
  http.patch('/api/alarm/settings/', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    stores.alarmSettings = { ...stores.alarmSettings, ...body }
    return ok(stores.alarmSettings)
  }),
  http.get('/api/alarm/settings/registry/', () => ok(demoSettingsRegistry)),
  http.get('/api/alarm/settings/profiles/', () => ok(stores.alarmProfiles, { total: stores.alarmProfiles.length })),
  http.post('/api/alarm/settings/profiles/', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as { name?: string }
    const now = new Date().toISOString()
    const created = {
      id: nextDemoId(),
      name: body.name ?? 'New Profile',
      is_active: false,
      created_at: now,
      updated_at: now,
    }
    stores.alarmProfiles = [...stores.alarmProfiles, created]
    return ok(created)
  }),
  http.patch('/api/alarm/settings/profiles/:id/', async ({ params, request }) => {
    const id = Number(params.id)
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    const now = new Date().toISOString()
    stores.alarmProfiles = stores.alarmProfiles.map((p) =>
      p.id === id ? { ...p, ...body, updated_at: now } : p,
    )
    return ok(stores.alarmProfiles.find((p) => p.id === id) ?? null)
  }),
  http.delete('/api/alarm/settings/profiles/:id/', ({ params }) => {
    const id = Number(params.id)
    stores.alarmProfiles = stores.alarmProfiles.filter((p) => p.id !== id)
    return ok(null)
  }),
  http.post('/api/alarm/settings/profiles/:id/activate/', ({ params }) => {
    const id = Number(params.id)
    stores.alarmProfiles = stores.alarmProfiles.map((p) => ({ ...p, is_active: p.id === id }))
    return ok(stores.alarmProfiles.find((p) => p.id === id) ?? null)
  }),

  // ── Sensors / Entities ──────────────────────────────────────────────────
  http.get('/api/alarm/sensors/', () => ok(stores.sensors, { total: stores.sensors.length })),
  http.get('/api/alarm/entities/', () =>
    ok(stores.haEntities, { total: stores.haEntities.length }),
  ),
  http.post('/api/alarm/entities/sync/', async () => {
    await delay(400)
    return ok({ synced: stores.haEntities.length })
  }),

  // ── Rules ───────────────────────────────────────────────────────────────
  http.get('/api/alarm/rules/', () => ok(stores.rules, { total: stores.rules.length })),
  http.post('/api/alarm/rules/', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    const created = { id: nextDemoId(), priority: 50, enabled: true, kind: 'trigger', stop_processing: false, stop_group: null, schema_version: 1, cooldown_seconds: 0, entity_ids: [], definition: { when: {}, then: [] }, created_by: 'user-admin', ...body, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
    stores.rules = [...stores.rules, created]
    return ok(created)
  }),
  http.patch('/api/alarm/rules/:id/', async ({ params, request }) => {
    const id = Number(params.id)
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    stores.rules = stores.rules.map((r) => (r.id === id ? { ...r, ...body } : r))
    return ok(stores.rules.find((r) => r.id === id) ?? null)
  }),
  http.delete('/api/alarm/rules/:id/', ({ params }) => {
    const id = Number(params.id)
    stores.rules = stores.rules.filter((r) => r.id !== id)
    return ok(null)
  }),
  http.post('/api/alarm/rules/run/', () => ok({ executed: true, matched: [] })),
  http.post('/api/alarm/rules/simulate/', () => ok({ matched: stores.rules.slice(0, 1), actions: [] })),
  http.get('/api/alarm/rules/stop-groups/', () => ok(['critical', 'maintenance'])),

  // ── User codes ──────────────────────────────────────────────────────────
  http.get('/api/codes/', () => ok(stores.userCodes, { total: stores.userCodes.length })),
  http.post('/api/codes/', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    const created = { id: nextDemoId(), is_active: true, allowed_states: [], usage_count: 0, ...body, created_at: new Date().toISOString() }
    stores.userCodes = [...stores.userCodes, created]
    return ok(created)
  }),
  http.patch('/api/codes/:id/', async ({ params, request }) => {
    const id = Number(params.id)
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    stores.userCodes = stores.userCodes.map((c) => (c.id === id ? { ...c, ...body } : c))
    return ok(stores.userCodes.find((c) => c.id === id) ?? null)
  }),
  http.delete('/api/codes/:id/', ({ params }) => {
    const id = Number(params.id)
    stores.userCodes = stores.userCodes.filter((c) => c.id !== id)
    return ok(null)
  }),
  http.get('/api/codes/:id/usage/', () => ok([])),

  // ── Door codes ──────────────────────────────────────────────────────────
  http.get('/api/door-codes/', () => ok(stores.doorCodes, { total: stores.doorCodes.length })),
  http.post('/api/door-codes/', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    const created = { id: nextDemoId(), is_active: true, days_of_week: [0,1,2,3,4,5,6], usage_count: 0, ...body, created_at: new Date().toISOString() }
    stores.doorCodes = [...stores.doorCodes, created]
    return ok(created)
  }),
  http.patch('/api/door-codes/:id/', async ({ params, request }) => {
    const id = Number(params.id)
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    stores.doorCodes = stores.doorCodes.map((c) => (c.id === id ? { ...c, ...body } : c))
    return ok(stores.doorCodes.find((c) => c.id === id) ?? null)
  }),
  http.delete('/api/door-codes/:id/', ({ params }) => {
    const id = Number(params.id)
    stores.doorCodes = stores.doorCodes.filter((c) => c.id !== id)
    return ok(null)
  }),

  // ── Locks ───────────────────────────────────────────────────────────────
  http.get('/api/locks/available/', () =>
    ok([
      { entity_id: 'lock.front_door', friendly_name: 'Front Door Lock', max_codes: 30 },
      { entity_id: 'lock.back_door', friendly_name: 'Back Door Lock', max_codes: 30 },
    ]),
  ),
  // Shape mirrors `LockConfigSyncResult` from `frontend/src/types/doorCode.ts`.
  // `useSyncLockConfigMutation.onSuccess` reads `data.dryRun` so the
  // `dry_run` field must be present on the wire.
  http.post('/api/locks/:lockEntityId/sync-config/', async ({ params, request }) => {
    const lockEntityId = String(params.lockEntityId)
    const url = new URL(request.url)
    const dryRun = url.searchParams.get('dry_run') === 'true'
    await delay(400)
    return ok({
      lock_entity_id: lockEntityId,
      node_id: 7,
      created: 0,
      updated: 0,
      unchanged: 2,
      skipped: 0,
      deactivated: 0,
      errors: 0,
      timestamp: new Date().toISOString(),
      slots: [],
      dry_run: dryRun,
    })
  }),

  // ── Events ──────────────────────────────────────────────────────────────
  http.get('/api/events/', ({ request }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') ?? 1)
    const pageSize = Number(url.searchParams.get('page_size') ?? 25)
    const start = (page - 1) * pageSize
    return ok(stores.events.slice(start, start + pageSize), {
      total: stores.events.length,
      page,
      page_size: pageSize,
      total_pages: Math.ceil(stores.events.length / pageSize),
      has_next: start + pageSize < stores.events.length,
      has_previous: page > 1,
    })
  }),
  // `alarmService.acknowledgeEvent` issues PATCH (`frontend/src/services/alarm.ts`).
  // Returning the updated event lets the Events UI paint the acknowledged
  // state without a refetch round-trip.
  http.patch('/api/events/:id/acknowledge/', ({ params }) => {
    const id = Number(params.id)
    stores.events = stores.events.map((e) =>
      e.id === id ? { ...e, acknowledged_at: new Date().toISOString() } : e,
    )
    return ok(stores.events.find((e) => e.id === id) ?? null)
  }),

  // ── Control panels ──────────────────────────────────────────────────────
  http.get('/api/control-panels/', () =>
    ok(stores.controlPanels, { total: stores.controlPanels.length }),
  ),
  http.patch('/api/control-panels/:id/', async ({ params, request }) => {
    const id = Number(params.id)
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    stores.controlPanels = stores.controlPanels.map((p) => (p.id === id ? { ...p, ...body } : p))
    return ok(stores.controlPanels.find((p) => p.id === id) ?? null)
  }),
  http.post('/api/control-panels/:id/test/', async () => {
    await delay(400)
    return ok({ success: true, message: 'Demo: button press simulated' })
  }),

  // ── Scheduler ───────────────────────────────────────────────────────────
  http.get('/api/scheduler/status/', () =>
    ok({ tasks: stores.schedulerTasks }, { total: stores.schedulerTasks.length }),
  ),
  http.get('/api/scheduler/tasks/:name/runs/', () => ok([])),

  // ── Notifications ───────────────────────────────────────────────────────
  http.get('/api/notifications/providers/', () =>
    ok(stores.notificationProviders, { total: stores.notificationProviders.length }),
  ),
  http.post('/api/notifications/providers/', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    const created = { id: `provider-${nextDemoId()}`, is_active: true, is_default: false, config: {}, ...body }
    stores.notificationProviders = [...stores.notificationProviders, created]
    return ok(created)
  }),
  http.patch('/api/notifications/providers/:id/', async ({ params, request }) => {
    const id = String(params.id)
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    stores.notificationProviders = stores.notificationProviders.map((p) =>
      p.id === id ? { ...p, ...body } : p,
    )
    return ok(stores.notificationProviders.find((p) => p.id === id) ?? null)
  }),
  http.delete('/api/notifications/providers/:id/', ({ params }) => {
    const id = String(params.id)
    stores.notificationProviders = stores.notificationProviders.filter((p) => p.id !== id)
    return ok(null)
  }),
  http.post('/api/notifications/providers/:id/test/', async () => {
    await delay(500)
    return ok({ success: true, message: 'Demo: test notification sent' })
  }),
  http.get('/api/notifications/provider-types/', () =>
    ok([
      {
        provider_type: 'pushbullet',
        display_name: 'Pushbullet',
        encrypted_fields: ['access_token'],
        config_schema: {
          type: 'object',
          required: ['access_token'],
          properties: {
            access_token: { type: 'string', title: 'Access Token', secret: true, description: 'Get from pushbullet.com → Settings → Access Tokens' },
            target_type: { type: 'string', title: 'Default Target', enum: ['all', 'device', 'email', 'channel'], default: 'all' },
          },
        },
      },
      {
        provider_type: 'discord',
        display_name: 'Discord Webhook',
        encrypted_fields: [],
        config_schema: {
          type: 'object',
          required: ['webhook_url'],
          properties: {
            webhook_url: { type: 'string', title: 'Webhook URL', description: 'Right-click channel → Edit Channel → Integrations → Webhooks' },
            username: { type: 'string', title: 'Bot Username', description: 'Override the webhook\'s default username' },
          },
        },
      },
      {
        provider_type: 'slack',
        display_name: 'Slack Webhook',
        encrypted_fields: ['bot_token'],
        config_schema: {
          type: 'object',
          required: ['bot_token', 'default_channel'],
          properties: {
            bot_token: { type: 'string', title: 'Bot Token', secret: true, description: 'Slack Bot token (starts with xoxb-)' },
            default_channel: { type: 'string', title: 'Default Channel', description: 'Slack channel ID (e.g., C0123456789)' },
          },
        },
      },
      {
        provider_type: 'webhook',
        display_name: 'Generic Webhook',
        encrypted_fields: [],
        config_schema: {
          type: 'object',
          required: ['url', 'method'],
          properties: {
            url: { type: 'string', title: 'Webhook URL', format: 'uri', description: 'The endpoint URL to send notifications to' },
            method: { type: 'string', title: 'HTTP Method', enum: ['POST', 'PUT'], default: 'POST' },
            content_type: { type: 'string', title: 'Content Type', enum: ['application/json', 'application/x-www-form-urlencoded'], default: 'application/json' },
          },
        },
      },
      {
        provider_type: 'home_assistant',
        display_name: 'Home Assistant',
        encrypted_fields: [],
        config_schema: { type: 'object', properties: {} },
      },
    ]),
  ),
  http.get('/api/notifications/pushbullet/devices/', () =>
    ok([
      { iden: 'demo-device-1', nickname: "Admin's Phone" },
      { iden: 'demo-device-2', nickname: "Resident's Tablet" },
    ]),
  ),
  http.post('/api/notifications/pushbullet/validate-token/', () => ok({ valid: true })),

  // ── Integration: Home Assistant ─────────────────────────────────────────
  // Settings/status shapes mirror `HomeAssistantStatus` and
  // `HomeAssistantConnectionSettings` from `frontend/src/services/homeAssistant.ts`.
  http.get('/api/alarm/home-assistant/status/', () => ok(stores.integrationHealth.home_assistant)),
  http.get('/api/alarm/home-assistant/settings/', () =>
    ok({
      enabled: true,
      base_url: 'http://homeassistant.demo.local:8123',
      connect_timeout_seconds: 10,
      has_token: true,
    }),
  ),
  http.patch('/api/alarm/home-assistant/settings/', async () => {
    await delay(300)
    return ok({
      enabled: true,
      base_url: 'http://homeassistant.demo.local:8123',
      connect_timeout_seconds: 10,
      has_token: true,
    })
  }),
  http.get('/api/alarm/home-assistant/entities/', () => ok(stores.haEntities)),
  http.get('/api/alarm/home-assistant/notify-services/', () =>
    ok(['notify.mobile_app_admin_phone', 'notify.discord_family', 'notify.slack_home']),
  ),

  // ── Integration: MQTT ───────────────────────────────────────────────────
  // Status/settings shapes mirror `MqttStatus` and `MqttSettings` from
  // `frontend/src/types/mqtt.ts`.
  http.get('/api/alarm/mqtt/status/', () => ok(stores.integrationHealth.mqtt)),
  http.get('/api/alarm/mqtt/settings/', () =>
    ok({
      enabled: true,
      host: 'broker.demo.local',
      port: 8883,
      username: 'latchpoint',
      use_tls: true,
      tls_insecure: false,
      client_id: 'latchpoint-demo',
      keepalive_seconds: 60,
      connect_timeout_seconds: 10,
      has_password: true,
    }),
  ),
  http.patch('/api/alarm/mqtt/settings/', async () => {
    await delay(300)
    return ok({
      enabled: true,
      host: 'broker.demo.local',
      port: 8883,
      username: 'latchpoint',
      use_tls: true,
      tls_insecure: false,
      client_id: 'latchpoint-demo',
      keepalive_seconds: 60,
      connect_timeout_seconds: 10,
      has_password: true,
    })
  }),
  http.post('/api/alarm/mqtt/test/', async () => {
    await delay(600)
    return ok({ success: true, message: 'Demo: MQTT broker reachable' })
  }),

  // ── Integration: HA MQTT alarm entity ───────────────────────────────────
  // Shapes mirror `HomeAssistantMqttAlarmEntitySettings`,
  // `HomeAssistantMqttAlarmEntityStatusResponse`, and the publishDiscovery
  // `{ ok: boolean }` return from `frontend/src/services/integrations.ts`.
  http.get('/api/alarm/integrations/home-assistant/mqtt-alarm-entity/', () =>
    ok({
      enabled: true,
      entity_name: 'Latchpoint Demo Alarm',
      also_rename_in_home_assistant: true,
      ha_entity_id: 'alarm_control_panel.latchpoint_demo_alarm',
    }),
  ),
  http.patch('/api/alarm/integrations/home-assistant/mqtt-alarm-entity/', async ({ request }) => {
    await delay(300)
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>
    return ok({
      enabled: true,
      entity_name: 'Latchpoint Demo Alarm',
      also_rename_in_home_assistant: true,
      ha_entity_id: 'alarm_control_panel.latchpoint_demo_alarm',
      ...body,
    })
  }),
  http.get('/api/alarm/integrations/home-assistant/mqtt-alarm-entity/status/', () =>
    ok({
      settings: {
        enabled: true,
        entity_name: 'Latchpoint Demo Alarm',
        also_rename_in_home_assistant: true,
        ha_entity_id: 'alarm_control_panel.latchpoint_demo_alarm',
      },
      status: {
        last_discovery_publish_at: new Date(Date.now() - 6 * 3600_000).toISOString(),
        last_state_publish_at: new Date(Date.now() - 30 * 60_000).toISOString(),
        last_availability_publish_at: new Date(Date.now() - 30 * 60_000).toISOString(),
        last_error_at: null,
        last_error: null,
      },
    }),
  ),
  http.post('/api/alarm/integrations/home-assistant/mqtt-alarm-entity/publish-discovery/', () =>
    ok({ ok: true }),
  ),

  // ── Integration: Z-Wave JS ──────────────────────────────────────────────
  // Status/settings shapes mirror `ZwavejsStatus` and `ZwavejsSettings` from
  // `frontend/src/types/zwavejs.ts`.
  http.get('/api/alarm/zwavejs/status/', () => ok(stores.integrationHealth.zwavejs)),
  http.get('/api/alarm/zwavejs/nodes/', () => ok(stores.zwaveNodes, { total: stores.zwaveNodes.length })),
  http.get('/api/alarm/zwavejs/settings/', () =>
    ok({
      enabled: true,
      ws_url: 'ws://zwavejs.demo.local:3000',
      connect_timeout_seconds: 10,
      reconnect_min_seconds: 5,
      reconnect_max_seconds: 60,
      has_api_token: false,
    }),
  ),
  http.patch('/api/alarm/zwavejs/settings/', async () => {
    await delay(300)
    return ok({
      enabled: true,
      ws_url: 'ws://zwavejs.demo.local:3000',
      connect_timeout_seconds: 10,
      reconnect_min_seconds: 5,
      reconnect_max_seconds: 60,
      has_api_token: false,
    })
  }),
  http.post('/api/alarm/zwavejs/test/', async () => {
    await delay(500)
    return ok({ success: true, message: 'Demo: controller reachable, 8 nodes online' })
  }),
  http.post('/api/alarm/zwavejs/entities/sync/', async () => {
    await delay(400)
    return ok({ synced: stores.zwaveNodes.length })
  }),

  // ── Integration: Zigbee2MQTT ────────────────────────────────────────────
  // Status/settings shapes mirror `Zigbee2mqttStatus` and `Zigbee2mqttSettings`
  // from `frontend/src/types/zigbee2mqtt.ts`. Note: `Zigbee2mqttStatus` nests a
  // `MqttStatus` under `mqtt` — the fixture includes it.
  http.get('/api/alarm/integrations/zigbee2mqtt/status/', () => ok(stores.integrationHealth.zigbee2mqtt)),
  http.get('/api/alarm/integrations/zigbee2mqtt/settings/', () =>
    ok({
      enabled: true,
      base_topic: 'zigbee2mqtt',
      allowlist: [],
      denylist: [],
      run_rules_on_event: false,
      run_rules_debounce_seconds: 30,
      run_rules_max_per_minute: 10,
      run_rules_kinds: [],
    }),
  ),
  http.patch('/api/alarm/integrations/zigbee2mqtt/settings/', async () => {
    await delay(300)
    return ok({
      enabled: true,
      base_topic: 'zigbee2mqtt',
      allowlist: [],
      denylist: [],
      run_rules_on_event: false,
      run_rules_debounce_seconds: 30,
      run_rules_max_per_minute: 10,
      run_rules_kinds: [],
    })
  }),
  http.get('/api/alarm/integrations/zigbee2mqtt/devices/', () =>
    ok(stores.zigbeeDevices, { total: stores.zigbeeDevices.length }),
  ),
  http.post('/api/alarm/integrations/zigbee2mqtt/devices/sync/', async () => {
    await delay(400)
    return ok({ synced: stores.zigbeeDevices.length })
  }),

  // ── Integration: Frigate ────────────────────────────────────────────────
  // Status/settings shapes mirror `FrigateStatus` and `FrigateSettings` from
  // `frontend/src/types/frigate.ts`. Note: `FrigateStatus` nests a `MqttStatus`
  // under `mqtt` — the fixture includes it.
  http.get('/api/alarm/integrations/frigate/status/', () => ok(stores.integrationHealth.frigate)),
  http.get('/api/alarm/integrations/frigate/settings/', () =>
    ok({
      enabled: true,
      events_topic: 'frigate/events',
      retention_seconds: 30 * 24 * 3600,
      run_rules_on_event: true,
      run_rules_debounce_seconds: 30,
      run_rules_max_per_minute: 10,
      run_rules_kinds: ['person', 'car'],
      known_cameras: stores.frigateCameras.map((c) => (c as { name: string }).name),
      known_zones_by_camera: Object.fromEntries(
        stores.frigateCameras.map((c) => [
          (c as { name: string }).name,
          (c as { zones: string[] }).zones,
        ]),
      ),
    }),
  ),
  http.patch('/api/alarm/integrations/frigate/settings/', async () => {
    await delay(300)
    return ok({
      enabled: true,
      events_topic: 'frigate/events',
      retention_seconds: 30 * 24 * 3600,
      run_rules_on_event: true,
      run_rules_debounce_seconds: 30,
      run_rules_max_per_minute: 10,
      run_rules_kinds: ['person', 'car'],
      known_cameras: stores.frigateCameras.map((c) => (c as { name: string }).name),
      known_zones_by_camera: Object.fromEntries(
        stores.frigateCameras.map((c) => [
          (c as { name: string }).name,
          (c as { zones: string[] }).zones,
        ]),
      ),
    })
  }),
  http.get('/api/alarm/integrations/frigate/options/', () =>
    ok({ cameras: stores.frigateCameras }),
  ),
  http.get('/api/alarm/integrations/frigate/detections/', () =>
    ok(stores.frigateDetections, { total: stores.frigateDetections.length }),
  ),

  // ── Debug ───────────────────────────────────────────────────────────────
  http.get('/api/alarm/debug/logs/', () =>
    ok([
      { ts: new Date().toISOString(), level: 'INFO', logger: 'alarm.state', message: '[demo] Alarm state machine ready' },
      { ts: new Date().toISOString(), level: 'INFO', logger: 'mqtt.manager', message: '[demo] MQTT broker connected (broker.demo.local:1883)' },
      { ts: new Date().toISOString(), level: 'INFO', logger: 'zwave.manager', message: '[demo] Z-Wave JS WS connected, 8 nodes synced' },
      { ts: new Date().toISOString(), level: 'WARN', logger: 'frigate.events', message: '[demo] Detection from camera "backyard" (dog, 0.91 conf)' },
    ]),
  ),

  // ── Catchall ────────────────────────────────────────────────────────────
  // Returns a success envelope for any other /api/* request so the app never
  // sees an unhandled-network error in demo mode: GET → `{data: []}` (safe for
  // list-shaped consumers), other methods → `{data: null}`. Add a specific
  // handler above when a page needs real data.
  http.all('/api/*', ({ request }) => {
    if (request.method === 'GET') return ok([])
    return ok(null)
  }),
]
