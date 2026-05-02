/**
 * Demo-mode fixtures. Hand-crafted snake_case data shaped to mirror what the
 * Django backend would return. The ApiClient's transformKeysDeep auto-converts
 * to camelCase before reaching React.
 *
 * MVP scope: enough to render every page without errors. Variety per page is
 * intentionally light on first cut; expand the inventory tables here as the
 * demo's narrative needs grow (per ADR-0089).
 */

export const demoUsers = [
  {
    id: 'user-admin',
    email: 'admin@demo.latchpoint.app',
    display_name: 'Demo Admin',
    role: 'admin',
    is_active: true,
    has_2fa: false,
    created_at: '2026-01-01T00:00:00Z',
    last_login: '2026-05-02T09:15:00Z',
  },
  {
    id: 'user-resident',
    email: 'resident@demo.latchpoint.app',
    display_name: 'Alex Resident',
    role: 'resident',
    is_active: true,
    has_2fa: false,
    created_at: '2026-01-15T00:00:00Z',
    last_login: '2026-05-01T18:42:00Z',
  },
  {
    id: 'user-guest',
    email: 'guest@demo.latchpoint.app',
    display_name: 'Casey Guest',
    role: 'guest',
    is_active: true,
    has_2fa: false,
    created_at: '2026-04-01T00:00:00Z',
    last_login: '2026-05-02T07:00:00Z',
  },
  {
    id: 'user-service',
    email: 'service@demo.latchpoint.app',
    display_name: 'House Cleaning Service',
    role: 'service',
    is_active: true,
    has_2fa: false,
    created_at: '2026-02-01T00:00:00Z',
    last_login: '2026-04-30T14:00:00Z',
  },
] as const

export type DemoUser = (typeof demoUsers)[number]

export const demoAlarmState = {
  state: 'disarmed',
  previous_state: 'armed_away',
  state_changed_at: '2026-05-02T08:30:00Z',
  pending_state: null,
  pending_seconds_remaining: 0,
  active_profile_id: 1,
  active_profile_name: 'Default',
  triggered_by: null,
  triggered_at: null,
}

export const demoAlarmSettings = {
  entry_delay_seconds: 30,
  exit_delay_seconds: 60,
  auto_arm_enabled: false,
  pin_required_for_disarm: true,
}

export const demoAlarmProfiles = [
  { id: 1, name: 'Default', is_active: true, entry_delay_seconds: 30, exit_delay_seconds: 60 },
  { id: 2, name: 'Vacation', is_active: false, entry_delay_seconds: 5, exit_delay_seconds: 10 },
  { id: 3, name: 'Sleep', is_active: false, entry_delay_seconds: 45, exit_delay_seconds: 30 },
]

export const demoIntegrationHealth = {
  home_assistant: {
    connected: true,
    last_heartbeat: new Date().toISOString(),
    entity_count: 32,
    version: '2026.4.2',
    url: 'http://homeassistant.demo.local:8123',
  },
  mqtt: {
    connected: true,
    broker: 'mqtt://broker.demo.local:1883',
    last_message_at: new Date().toISOString(),
    messages_per_minute: 47,
    tls_enabled: true,
  },
  zwavejs: {
    connected: true,
    controller_node_id: 1,
    device_count: 8,
    ws_url: 'ws://zwavejs.demo.local:3000',
    last_event_at: new Date().toISOString(),
  },
  zigbee2mqtt: {
    connected: true,
    device_count: 8,
    last_event_at: new Date().toISOString(),
    base_topic: 'zigbee2mqtt',
  },
  frigate: {
    connected: true,
    camera_count: 4,
    last_detection_at: new Date(Date.now() - 12 * 60_000).toISOString(),
    url: 'http://frigate.demo.local:5000',
    version: '0.14.1',
  },
}

export const demoSensors = [
  { id: 1, name: 'Front Door', entity_id: 'binary_sensor.front_door', sensor_type: 'door', state: 'closed', enabled: true, location: 'Entry', tags: ['Doors', 'Critical'] },
  { id: 2, name: 'Back Door', entity_id: 'binary_sensor.back_door', sensor_type: 'door', state: 'closed', enabled: true, location: 'Kitchen', tags: ['Doors'] },
  { id: 3, name: 'Garage Door', entity_id: 'binary_sensor.garage_door', sensor_type: 'door', state: 'closed', enabled: true, location: 'Garage', tags: ['Doors'] },
  { id: 4, name: 'Living Room Window', entity_id: 'binary_sensor.lr_window', sensor_type: 'window', state: 'closed', enabled: true, location: 'Living Room', tags: [] },
  { id: 5, name: 'Bedroom Window', entity_id: 'binary_sensor.bd_window', sensor_type: 'window', state: 'closed', enabled: true, location: 'Bedroom', tags: [] },
  { id: 6, name: 'Hallway Motion', entity_id: 'binary_sensor.hall_motion', sensor_type: 'motion', state: 'idle', enabled: true, location: 'Hallway', tags: ['Motion'] },
  { id: 7, name: 'Backyard Motion', entity_id: 'binary_sensor.backyard_motion', sensor_type: 'motion', state: 'idle', enabled: true, location: 'Backyard', tags: ['Motion', 'Outdoor'] },
  { id: 8, name: 'Glass Break Sensor', entity_id: 'binary_sensor.glass_break', sensor_type: 'glass_break', state: 'idle', enabled: true, location: 'Living Room', tags: ['Critical'] },
  { id: 9, name: 'Kitchen Smoke Alarm', entity_id: 'binary_sensor.kitchen_smoke', sensor_type: 'smoke', state: 'normal', enabled: true, location: 'Kitchen', tags: ['Critical'] },
  { id: 10, name: 'Basement Water Leak', entity_id: 'binary_sensor.basement_water', sensor_type: 'water', state: 'dry', enabled: true, location: 'Basement', tags: [] },
]

export const demoUserCodes = [
  { id: 1, label: "Admin's PIN", user_id: 'user-admin', code_type: 'permanent', is_active: true, allowed_states: [], usage_count: 142, created_at: '2026-01-01T00:00:00Z', last_used_at: '2026-05-02T09:15:00Z' },
  { id: 2, label: "Resident's PIN", user_id: 'user-resident', code_type: 'permanent', is_active: true, allowed_states: [], usage_count: 89, created_at: '2026-01-15T00:00:00Z', last_used_at: '2026-05-01T22:30:00Z' },
  { id: 3, label: 'Guest Weekend Stay', user_id: 'user-guest', code_type: 'temporary', is_active: true, allowed_states: ['armed_home', 'disarmed'], usage_count: 3, expires_at: '2026-05-05T23:59:59Z', created_at: '2026-05-01T00:00:00Z', last_used_at: '2026-05-02T07:00:00Z' },
  { id: 4, label: 'House Cleaner', user_id: 'user-service', code_type: 'service', is_active: true, allowed_states: ['disarmed', 'armed_home'], usage_count: 12, created_at: '2026-02-01T00:00:00Z', last_used_at: '2026-04-30T14:00:00Z' },
  { id: 5, label: 'Maintenance One-Time', user_id: 'user-service', code_type: 'one_time', is_active: false, allowed_states: ['disarmed'], usage_count: 1, created_at: '2026-03-15T00:00:00Z', last_used_at: '2026-03-15T10:30:00Z' },
  { id: 6, label: 'Night Mode Override', user_id: 'user-resident', code_type: 'permanent', is_active: true, allowed_states: ['armed_night'], usage_count: 24, created_at: '2026-02-01T00:00:00Z', last_used_at: '2026-05-01T23:45:00Z' },
]

export const demoDoorCodes = [
  { id: 1, label: 'Resident Daily', lock_entity_id: 'lock.front_door', slot: 1, code_type: 'permanent', is_active: true, days_of_week: [0,1,2,3,4,5,6], usage_count: 87, max_uses: null, time_window_start: null, time_window_end: null, created_at: '2026-01-15T00:00:00Z' },
  { id: 2, label: 'Cleaner Weekly', lock_entity_id: 'lock.front_door', slot: 2, code_type: 'service', is_active: true, days_of_week: [3], usage_count: 12, max_uses: null, time_window_start: '09:00', time_window_end: '13:00', created_at: '2026-02-01T00:00:00Z' },
  { id: 3, label: 'Guest Weekend', lock_entity_id: 'lock.back_door', slot: 1, code_type: 'temporary', is_active: true, days_of_week: [5,6], usage_count: 3, max_uses: 20, time_window_start: null, time_window_end: null, expires_at: '2026-05-05T23:59:59Z', created_at: '2026-05-01T00:00:00Z' },
  { id: 4, label: 'Delivery One-Time', lock_entity_id: 'lock.front_door', slot: 3, code_type: 'one_time', is_active: false, days_of_week: [], usage_count: 1, max_uses: 1, created_at: '2026-04-01T00:00:00Z' },
  { id: 5, label: 'Spare Key', lock_entity_id: 'lock.back_door', slot: 2, code_type: 'permanent', is_active: true, days_of_week: [0,1,2,3,4,5,6], usage_count: 0, max_uses: 5, created_at: '2026-03-01T00:00:00Z' },
]

export const demoRules = [
  { id: 1, name: 'Front Door Open While Armed Away', description: 'Trigger alarm if front door opens while armed away', kind: 'trigger', priority: 100, is_enabled: true, stop_group: null, cooldown_seconds: 0, definition: { when: { combinator: 'and', rules: [] }, then: [{ type: 'send_notification' }] }, created_at: '2026-01-10T00:00:00Z' },
  { id: 2, name: 'Glass Break = Immediate Trigger', description: 'No entry delay for glass break events', kind: 'trigger', priority: 90, is_enabled: true, stop_group: 'critical', cooldown_seconds: 0, definition: { when: {}, then: [] }, created_at: '2026-01-12T00:00:00Z' },
  { id: 3, name: 'Smoke Detected', description: 'Notify everyone on smoke', kind: 'escalate', priority: 95, is_enabled: true, stop_group: 'critical', cooldown_seconds: 60, definition: { when: {}, then: [] }, created_at: '2026-01-15T00:00:00Z' },
  { id: 4, name: 'Auto-Arm at 11 PM', description: 'Switch to armed_night every night at 23:00', kind: 'arm', priority: 50, is_enabled: true, stop_group: null, cooldown_seconds: 0, definition: { when: {}, then: [] }, created_at: '2026-02-01T00:00:00Z' },
  { id: 5, name: 'Disarm on Guest Code', description: 'Auto-disarm if guest code used', kind: 'disarm', priority: 60, is_enabled: true, stop_group: null, cooldown_seconds: 0, definition: { when: {}, then: [] }, created_at: '2026-02-10T00:00:00Z' },
  { id: 6, name: 'Suppress Backyard Motion at Night', description: 'Pet causes false positives', kind: 'suppress', priority: 40, is_enabled: true, stop_group: null, cooldown_seconds: 0, definition: { when: {}, then: [] }, created_at: '2026-03-01T00:00:00Z' },
  { id: 7, name: 'Discord on Triggered', description: 'Notify Discord channel on any trigger', kind: 'trigger', priority: 30, is_enabled: true, stop_group: null, cooldown_seconds: 30, definition: { when: {}, then: [] }, created_at: '2026-03-15T00:00:00Z' },
  { id: 8, name: 'Service Code = Limited Hours', description: 'Reject service codes outside 9am-5pm', kind: 'suppress', priority: 70, is_enabled: false, stop_group: null, cooldown_seconds: 0, definition: { when: {}, then: [] }, created_at: '2026-04-01T00:00:00Z' },
]

export const demoEvents = Array.from({ length: 50 }, (_, i) => {
  const types = ['armed', 'disarmed', 'pending', 'triggered', 'code_used', 'sensor_triggered', 'state_changed']
  const offset = (i + 1) * 90 * 60_000
  return {
    id: 1000 - i,
    event_type: types[i % types.length],
    severity: i % 7 === 0 ? 'critical' : i % 3 === 0 ? 'warning' : 'info',
    description: `[demo] Event ${1000 - i} — ${types[i % types.length]}`,
    metadata: {},
    user_id: i % 4 === 0 ? 'user-admin' : null,
    sensor_id: i % 5 === 0 ? (i % 10) + 1 : null,
    created_at: new Date(Date.now() - offset).toISOString(),
    acknowledged_at: null,
  }
})

export const demoNotificationProviders = [
  { id: 'provider-pushbullet', name: 'My Pushbullet', handler_type: 'pushbullet', is_active: true, is_default: true, config: { api_key: 'enc:v1:demo-pushbullet-token-masked' } },
  { id: 'provider-discord', name: 'Family Discord', handler_type: 'discord', is_active: true, is_default: false, config: { webhook_url: 'https://discord.com/api/webhooks/demo' } },
  { id: 'provider-slack', name: 'Home Slack', handler_type: 'slack', is_active: true, is_default: false, config: { webhook_url: 'https://hooks.slack.com/services/demo' } },
  { id: 'provider-webhook', name: 'IFTTT Webhook', handler_type: 'webhook', is_active: true, is_default: false, config: { url: 'https://maker.ifttt.com/trigger/demo' } },
  { id: 'ha-system-provider', name: 'Home Assistant', handler_type: 'home_assistant', is_active: true, is_default: false, config: {} },
  { id: 'provider-pushbullet-secondary', name: 'Pushbullet (Backup)', handler_type: 'pushbullet', is_active: false, is_default: false, config: { api_key: 'enc:v1:demo-backup-token-masked' } },
]

export const demoControlPanels = [
  { id: 1, name: 'Front Door Keypad', device_type: 'ring_keypad_v2', node_id: 5, is_active: true, action_mapping: { '0': 'disarm', '1': 'arm_away', '2': 'arm_home', '3': 'arm_night' }, last_action_at: '2026-05-01T22:30:00Z' },
]

export const demoSchedulerTasks = [
  { task_name: 'sync_zwave_entities', enabled: true, cron: '*/15 * * * *', last_run_at: new Date(Date.now() - 5 * 60_000).toISOString(), last_status: 'success', next_run_at: new Date(Date.now() + 10 * 60_000).toISOString(), failure_count: 0 },
  { task_name: 'sync_ha_entities', enabled: true, cron: '0 */1 * * *', last_run_at: new Date(Date.now() - 30 * 60_000).toISOString(), last_status: 'success', next_run_at: new Date(Date.now() + 30 * 60_000).toISOString(), failure_count: 0 },
  { task_name: 'cleanup_expired_codes', enabled: true, cron: '0 3 * * *', last_run_at: new Date(Date.now() - 6 * 3600_000).toISOString(), last_status: 'success', next_run_at: new Date(Date.now() + 18 * 3600_000).toISOString(), failure_count: 0 },
  { task_name: 'notification_outbox_retry', enabled: true, cron: '*/5 * * * *', last_run_at: new Date(Date.now() - 2 * 60_000).toISOString(), last_status: 'failure', next_run_at: new Date(Date.now() + 3 * 60_000).toISOString(), failure_count: 2 },
  { task_name: 'frigate_event_poll', enabled: false, cron: '*/30 * * * * *', last_run_at: null, last_status: null, next_run_at: null, failure_count: 0 },
]

export const demoZwaveNodes = [
  { node_id: 2, name: 'Front Door Lock', product_label: 'Schlage BE469', is_locked: true, battery_level: 85 },
  { node_id: 3, name: 'Back Door Lock', product_label: 'Yale Assure', is_locked: true, battery_level: 67 },
  { node_id: 4, name: 'Hallway Motion', product_label: 'Aeotec MultiSensor 7', battery_level: 92 },
  { node_id: 5, name: 'Front Door Keypad', product_label: 'Ring Keypad v2', battery_level: 78 },
  { node_id: 6, name: 'Living Room Switch', product_label: 'GE In-Wall Switch' },
  { node_id: 7, name: 'Kitchen Smoke', product_label: 'First Alert ZCOMBO', battery_level: 88 },
  { node_id: 8, name: 'Basement MultiSensor', product_label: 'Aeotec MultiSensor 7', battery_level: 95 },
]

export const demoZigbeeDevices = [
  { friendly_name: 'living_room_bulb', model: 'IKEA Tradfri RGB', state: 'ON' },
  { friendly_name: 'kitchen_bulb', model: 'IKEA Tradfri White', state: 'OFF' },
  { friendly_name: 'bedroom_bulb', model: 'IKEA Tradfri Color', state: 'ON' },
  { friendly_name: 'office_window_contact', model: 'Aqara Door Sensor', state: 'closed' },
  { friendly_name: 'pantry_window_contact', model: 'Aqara Door Sensor', state: 'closed' },
  { friendly_name: 'garage_motion', model: 'Aqara Motion Sensor', state: 'no_motion' },
  { friendly_name: 'panic_button', model: 'IKEA Symfonisk Button' },
  { friendly_name: 'living_room_plug', model: 'Innr Smart Plug' },
]

export const demoFrigateCameras = [
  { name: 'front_door', enabled: true, zones: ['walkway', 'porch'] },
  { name: 'backyard', enabled: true, zones: ['lawn', 'patio', 'pool'] },
  { name: 'driveway', enabled: true, zones: ['driveway', 'street'] },
  { name: 'garage', enabled: true, zones: ['garage_interior'] },
]

export const demoFrigateDetections = Array.from({ length: 22 }, (_, i) => {
  const cameras = demoFrigateCameras.map((c) => c.name)
  const labels = ['person', 'car', 'package', 'dog']
  return {
    id: 9000 - i,
    camera: cameras[i % cameras.length],
    label: labels[i % labels.length],
    zone: 'walkway',
    score: 0.7 + (i % 30) / 100,
    started_at: new Date(Date.now() - (i + 1) * 17 * 60_000).toISOString(),
    ended_at: new Date(Date.now() - (i + 1) * 17 * 60_000 + 30_000).toISOString(),
    has_snapshot: true,
  }
})

export const demoHaEntities = [
  ...['light.living_room', 'light.kitchen', 'light.bedroom', 'light.office', 'light.porch', 'light.garage'].map((id) => ({ entity_id: id, friendly_name: id.split('.')[1].replace('_', ' '), state: 'on', domain: 'light' })),
  ...['switch.coffee_maker', 'switch.fan_office', 'switch.garage_outlet'].map((id) => ({ entity_id: id, friendly_name: id.split('.')[1], state: 'off', domain: 'switch' })),
  ...['sensor.outdoor_temperature', 'sensor.indoor_temperature', 'sensor.humidity_living', 'sensor.humidity_basement'].map((id, idx) => ({ entity_id: id, friendly_name: id.split('.')[1], state: String(60 + idx), domain: 'sensor', unit: '°F' })),
  ...['climate.main_thermostat', 'climate.upstairs_thermostat'].map((id) => ({ entity_id: id, friendly_name: id.split('.')[1], state: 'cool', domain: 'climate' })),
  ...['lock.front_door', 'lock.back_door'].map((id) => ({ entity_id: id, friendly_name: id.split('.')[1], state: 'locked', domain: 'lock' })),
  ...['cover.garage_door', 'cover.living_room_blinds'].map((id) => ({ entity_id: id, friendly_name: id.split('.')[1], state: 'closed', domain: 'cover' })),
  ...['binary_sensor.front_door', 'binary_sensor.back_door', 'binary_sensor.lr_window', 'binary_sensor.hall_motion', 'binary_sensor.glass_break', 'binary_sensor.kitchen_smoke'].map((id) => ({ entity_id: id, friendly_name: id.split('.')[1].replace(/_/g, ' '), state: 'off', domain: 'binary_sensor' })),
  ...['media_player.living_room_tv', 'media_player.kitchen_speaker'].map((id) => ({ entity_id: id, friendly_name: id.split('.')[1], state: 'idle', domain: 'media_player' })),
]

export const demoSettingsRegistry = [
  { key: 'mqtt', label: 'MQTT', description: 'Broker connection', config_schema: { fields: [] }, encrypted_fields: ['password'] },
  { key: 'home_assistant', label: 'Home Assistant', description: 'HA REST + WS', config_schema: { fields: [] }, encrypted_fields: ['token'] },
  { key: 'zwavejs', label: 'Z-Wave JS', description: 'WS bridge', config_schema: { fields: [] }, encrypted_fields: [] },
  { key: 'frigate', label: 'Frigate', description: 'NVR + detection', config_schema: { fields: [] }, encrypted_fields: [] },
  { key: 'zigbee2mqtt', label: 'Zigbee2MQTT', description: 'Bridge over MQTT', config_schema: { fields: [] }, encrypted_fields: [] },
]
