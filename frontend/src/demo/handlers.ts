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
 * else falls through to a catchall that returns `{data: null}` so unknown
 * endpoints don't crash the app. Expand specificity as needed.
 */

import { http, HttpResponse, delay } from 'msw'
import { stores, nextDemoId } from './stores'
import { demoUsers, demoSettingsRegistry } from './fixtures'

const ok = <T,>(data: T, meta?: Record<string, unknown>) =>
  HttpResponse.json(meta ? { data, meta } : { data })

const ADMIN = demoUsers[0]

export const handlers = [
  // ── Auth ────────────────────────────────────────────────────────────────
  // The CSRF cookie is primed once at startup in `initDemoMode()` (page
  // context). Handlers run in the Service Worker context where `document`
  // is undefined, so we must not write the cookie here.
  http.get('/api/auth/csrf/', () => ok(null)),

  http.post('/api/auth/login/', async () => {
    await delay(200)
    return ok({
      user: ADMIN,
      access_token: 'demo-access-token',
      refresh_token: 'demo-refresh-token',
      requires_2fa: false,
    })
  }),

  http.post('/api/auth/logout/', () => ok(null)),
  http.post('/api/auth/2fa/verify/', () => ok({ verified: true })),
  http.post('/api/auth/validate-code/', () => ok({ valid: true, user: ADMIN })),

  // ── Users ───────────────────────────────────────────────────────────────
  http.get('/api/users/me/', () => ok(ADMIN)),
  http.get('/api/users/', () => ok(demoUsers, { total: demoUsers.length })),

  // ── Onboarding / setup gate ─────────────────────────────────────────────
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
    const created = { id: nextDemoId(), priority: 50, is_enabled: true, kind: 'trigger', cooldown_seconds: 0, definition: { when: {}, then: [] }, ...body, created_at: new Date().toISOString() }
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
  http.post('/api/events/:id/acknowledge/', ({ params }) => {
    const id = Number(params.id)
    stores.events = stores.events.map((e) =>
      e.id === id ? { ...e, acknowledged_at: new Date().toISOString() } : e,
    )
    return ok(null)
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
      { handler_type: 'pushbullet', label: 'Pushbullet', config_schema: { fields: [] } },
      { handler_type: 'discord', label: 'Discord Webhook', config_schema: { fields: [] } },
      { handler_type: 'slack', label: 'Slack Webhook', config_schema: { fields: [] } },
      { handler_type: 'webhook', label: 'Generic Webhook', config_schema: { fields: [] } },
      { handler_type: 'home_assistant', label: 'Home Assistant', config_schema: { fields: [] } },
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
  // Returns an empty success envelope for any other /api/* request so the app
  // never sees an unhandled-network error in demo mode. Add a specific handler
  // above when a page needs real data.
  http.all('/api/*', ({ request }) => {
    if (request.method === 'GET') return ok([])
    return ok(null)
  }),
]
