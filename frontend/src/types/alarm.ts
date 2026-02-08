import type { AlarmStateType, EventTypeType } from '@/lib/constants'
import type { MqttStatus } from './mqtt'
import type { ZwavejsStatus } from './zwavejs'
import type { Zigbee2mqttStatus } from './zigbee2mqtt'
import type { FrigateStatus } from './frigate'

// Alarm State Snapshot
export interface AlarmStateSnapshot {
  id: number
  currentState: AlarmStateType
  previousState: AlarmStateType | null
  settingsProfile: number
  enteredAt: string // ISO datetime
  exitAt: string | null // ISO datetime, for timed transitions
  lastTransitionReason: string
  lastTransitionBy: string | null // User ID (UUID)
  targetArmedState: AlarmStateType | null
  timingSnapshot: {
    delayTime?: number
    armingTime?: number
    triggerTime?: number
  }
}

// Alarm Settings Profile
export interface AlarmSettingsProfile {
  id: number
  name: string
  isActive: boolean
  delayTime: number // seconds
  armingTime: number // seconds
  triggerTime: number // seconds
  disarmAfterTrigger: boolean
  codeArmRequired: boolean
  availableArmingStates: AlarmStateType[]
  stateOverrides: StateOverrides
  audioVisualSettings: AudioVisualSettings
  sensorBehavior: SensorBehavior
  homeAssistantNotify?: HomeAssistantNotifySettings
  createdAt: string
  updatedAt: string
}

export interface HomeAssistantNotifySettings {
  enabled: boolean
  service?: string
  services?: string[]
  cooldownSeconds?: number
  states: AlarmStateType[]
}

export interface StateOverrides {
  [state: string]: {
    delayTime?: number
    armingTime?: number
    triggerTime?: number
  }
}

export interface AudioVisualSettings {
  beepEnabled: boolean
  countdownDisplayEnabled: boolean
  colorCodingEnabled: boolean
}

export interface SensorBehavior {
  warnOnOpenSensors: boolean
  autoBypassEnabled: boolean
  forceArmEnabled: boolean
}

// Sensor
export interface Sensor {
  id: number
  name: string
  entityId: string | null // HA entity ID
  isActive: boolean
  isEntryPoint: boolean
  currentState: 'open' | 'closed' | 'unknown'
  lastTriggered: string | null
  usedInRules?: boolean
}

// Alarm Event
export interface AlarmEvent {
  id: number
  eventType: EventTypeType
  stateFrom: AlarmStateType | null
  stateTo: AlarmStateType | null
  timestamp: string
  userId: string | null
  codeId: number | null
  sensorId: number | null
  metadata: Record<string, unknown>
}

// Arm/Disarm Request
export interface ArmRequest {
  targetState: AlarmStateType
  code?: string
}

export interface DisarmRequest {
  code: string
}

// WebSocket Messages - Discriminated Union
export type AlarmWebSocketMessage =
  | {
      type: 'alarm_state'
      timestamp: string
      payload: AlarmStatePayload
      sequence: number
    }
  | {
      type: 'event'
      timestamp: string
      payload: AlarmEventPayload
      sequence: number
    }
  | {
      type: 'countdown'
      timestamp: string
      payload: CountdownPayload
      sequence: number
    }
  | {
      type: 'health'
      timestamp: string
      payload: HealthPayload
      sequence: number
    }
  | {
      type: 'system_status'
      timestamp: string
      payload: SystemStatusPayload
      sequence: number
    }
  | {
      type: 'entity_sync'
      timestamp: string
      payload: EntitySyncPayload
      sequence: number
    }

export interface EntitySyncEntity {
  entityId: string
  oldState: string | null
  newState: string | null
}

export interface EntitySyncPayload {
  entities: EntitySyncEntity[]
  count: number
}

export interface AlarmStatePayload {
  state: AlarmStateSnapshot
  effectiveSettings: {
    delayTime: number
    armingTime: number
    triggerTime: number
  }
}

export interface AlarmEventPayload {
  event: AlarmEvent
}

export interface CountdownPayload {
  type: 'entry' | 'exit' | 'trigger'
  remainingSeconds: number
  totalSeconds: number
}

export interface HealthPayload {
  status: 'healthy' | 'degraded' | 'unhealthy'
  timestamp: string
  details?: Record<string, unknown>
}

export interface SystemStatusPayload {
  homeAssistant: {
    configured: boolean
    reachable: boolean
    baseUrl?: string | null
    error?: string | null
  }
  mqtt: MqttStatus
  zwavejs: ZwavejsStatus
  zigbee2mqtt: Zigbee2mqttStatus
  frigate: FrigateStatus
}
