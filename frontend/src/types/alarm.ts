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
}

// Alarm Settings Profile (post ADR-0095: timing knobs live in rules, not the profile)
export interface AlarmSettingsProfile {
  id: number
  name: string
  isActive: boolean
  codeArmRequired: boolean
  availableArmingStates: AlarmStateType[]
  audioVisualSettings: AudioVisualSettings
  sensorBehavior: SensorBehavior
  createdAt: string
  updatedAt: string
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

// PendingAction queue (ADR-0091)
export type PendingActionStatusType = 'scheduled' | 'fired' | 'cancelled' | 'failed'
export type PendingActionCancelReasonType =
  | ''
  | 'disarm'
  | 'when_false'
  | 'manual'
  | 'rule_deleted'
  | 'stale_after_restart'

export interface PendingAction {
  id: number
  ruleId: number
  ruleName: string
  actionIndex: number
  actionPayload: Record<string, unknown>
  delaySeconds: number
  scheduledAt: string
  fireAt: string
  status: PendingActionStatusType
  cancelReason: PendingActionCancelReasonType
  firedAt: string | null
  fireResult: Record<string, unknown> | null
  armedStateAtSchedule: AlarmStateType
  actorUserEmail: string | null
  createdAt: string
  updatedAt: string
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
  | {
      type: 'log_entry'
      timestamp: string
      payload: LogEntryPayload
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

export interface LogEntryPayload {
  timestamp: string
  level: string
  levelNo: number
  logger: string
  message: string
  excText: string | null
  filename: string
  lineno: number
  funcName: string
  formatted: string
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
