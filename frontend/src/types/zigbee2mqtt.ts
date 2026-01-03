import type { MqttStatus } from './mqtt'
import type { Entity } from './rules'

export type AlarmState =
  | 'disarmed'
  | 'arming'
  | 'armed_home'
  | 'armed_away'
  | 'armed_night'
  | 'armed_vacation'
  | 'pending'
  | 'triggered'

export type ArmedState = 'armed_home' | 'armed_away' | 'armed_night' | 'armed_vacation'

export interface Zigbee2mqttSettings {
  enabled: boolean
  baseTopic: string
  allowlist?: unknown[]
  denylist?: unknown[]
  runRulesOnEvent?: boolean
  runRulesDebounceSeconds?: number
  runRulesMaxPerMinute?: number
  runRulesKinds?: string[]
}

export interface Zigbee2mqttSettingsUpdate {
  enabled?: boolean
  baseTopic?: string
  allowlist?: unknown[]
  denylist?: unknown[]
  runRulesOnEvent?: boolean
  runRulesDebounceSeconds?: number
  runRulesMaxPerMinute?: number
  runRulesKinds?: string[]
}

export interface Zigbee2mqttLastSync {
  lastSyncAt: string | null
  lastDeviceCount: number | null
  lastError: string | null
}

export interface Zigbee2mqttStatus {
  enabled: boolean
  baseTopic: string
  connected: boolean
  mqtt: MqttStatus
  sync: Zigbee2mqttLastSync
  runRulesOnEvent?: boolean
  runRulesDebounceSeconds?: number
  runRulesMaxPerMinute?: number
  runRulesKinds?: string[]
}

export interface Zigbee2mqttSyncResult {
  ok: boolean
  devices: number
  entitiesUpserted: number
}

export type Zigbee2mqttEntity = Entity
