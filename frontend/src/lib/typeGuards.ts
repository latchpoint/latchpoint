/**
 * Type guard functions for runtime type validation
 * These guards enable safe type narrowing and prevent unsafe type assertions
 */

import type {
  AlarmStateSnapshot,
  AlarmEvent,
  AlarmStatePayload,
  AlarmEventPayload,
  CountdownPayload,
  HealthPayload,
  SystemStatusPayload,
} from '@/types/alarm'
import type { AlarmStateType, EventTypeType } from '@/lib/constants'

// ============================================================================
// Basic Type Guards
// ============================================================================

/**
 * Check if value is a non-null object (not array)
 */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Check if value is a record with all string values
 */
export function isStringRecord(value: unknown): value is Record<string, string> {
  if (!isRecord(value)) return false
  return Object.values(value).every((v) => typeof v === 'string')
}

/**
 * Check if value is a string array
 */
export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

// ============================================================================
// Alarm State Type Guards
// ============================================================================

/**
 * Valid alarm state values
 */
const ALARM_STATES = [
  'disarmed',
  'arming',
  'armed_home',
  'armed_away',
  'armed_night',
  'armed_vacation',
  'armed_custom_bypass',
  'pending',
  'triggered',
] as const

/**
 * Check if value is a valid AlarmStateType
 */
export function isAlarmStateType(value: unknown): value is AlarmStateType {
  return typeof value === 'string' && ALARM_STATES.includes(value as AlarmStateType)
}

/**
 * Check if value is a valid EventTypeType
 */
const EVENT_TYPES = [
  'armed',
  'disarmed',
  'pending',
  'triggered',
  'code_used',
  'sensor_triggered',
  'failed_code',
  'state_changed',
  'scheduler_task_failed',
  'scheduler_task_stuck',
] as const

export function isEventTypeType(value: unknown): value is EventTypeType {
  return typeof value === 'string' && EVENT_TYPES.includes(value as EventTypeType)
}

/**
 * Check if value is a valid AlarmStateSnapshot
 */
export function isAlarmStateSnapshot(data: unknown): data is AlarmStateSnapshot {
  if (!isRecord(data)) return false

  return (
    typeof data.id === 'number' &&
    isAlarmStateType(data.currentState) &&
    (data.previousState === null || isAlarmStateType(data.previousState)) &&
    typeof data.settingsProfile === 'number' &&
    typeof data.enteredAt === 'string' &&
    (data.exitAt === null || typeof data.exitAt === 'string') &&
    typeof data.lastTransitionReason === 'string' &&
    (data.lastTransitionBy === null || typeof data.lastTransitionBy === 'string') &&
    (data.targetArmedState === null || isAlarmStateType(data.targetArmedState)) &&
    isRecord(data.timingSnapshot)
  )
}

/**
 * Check if value is a valid AlarmEvent
 */
export function isAlarmEvent(data: unknown): data is AlarmEvent {
  if (!isRecord(data)) return false

  return (
    typeof data.id === 'number' &&
    isEventTypeType(data.eventType) &&
    (data.stateFrom === null || isAlarmStateType(data.stateFrom)) &&
    (data.stateTo === null || isAlarmStateType(data.stateTo)) &&
    typeof data.timestamp === 'string' &&
    (data.userId === null || typeof data.userId === 'string') &&
    (data.codeId === null || typeof data.codeId === 'number') &&
    (data.sensorId === null || typeof data.sensorId === 'number') &&
    isRecord(data.metadata)
  )
}

// ============================================================================
// WebSocket Message Payload Guards
// ============================================================================

/**
 * Check if payload is an AlarmStatePayload
 */
export function isAlarmStatePayload(payload: unknown): payload is AlarmStatePayload {
  if (!isRecord(payload)) return false
  if (!('state' in payload)) return false

  const state = payload.state
  if (!isAlarmStateSnapshot(state)) return false

  if (!('effectiveSettings' in payload)) return false
  const settings = payload.effectiveSettings
  if (!isRecord(settings)) return false

  return (
    typeof settings.delayTime === 'number' &&
    typeof settings.armingTime === 'number' &&
    typeof settings.triggerTime === 'number'
  )
}

/**
 * Check if payload is an AlarmEventPayload
 */
export function isAlarmEventPayload(payload: unknown): payload is AlarmEventPayload {
  if (!isRecord(payload)) return false
  return 'event' in payload && isAlarmEvent(payload.event)
}

/**
 * Check if payload is a CountdownPayload
 */
export function isCountdownPayload(payload: unknown): payload is CountdownPayload {
  if (!isRecord(payload)) return false

  const { type, remainingSeconds, totalSeconds } = payload as Record<string, unknown>

  return (
    (type === 'entry' || type === 'exit' || type === 'trigger') &&
    typeof remainingSeconds === 'number' &&
    typeof totalSeconds === 'number'
  )
}

/**
 * Check if payload is a HealthPayload
 */
export function isHealthPayload(payload: unknown): payload is HealthPayload {
  if (!isRecord(payload)) return false

  const { status, timestamp } = payload as Record<string, unknown>

  return (
    (status === 'healthy' || status === 'degraded' || status === 'unhealthy') &&
    typeof timestamp === 'string'
  )
}

/**
 * Check if payload is a SystemStatusPayload.
 *
 * Intentionally validates only the booleans the UI depends on to avoid
 * duplicating all per-integration status schemas here.
 */
export function isSystemStatusPayload(payload: unknown): payload is SystemStatusPayload {
  if (!isRecord(payload)) return false

  const { homeAssistant, mqtt, zwavejs, zigbee2mqtt, frigate } = payload as Record<string, unknown>
  if (!isRecord(homeAssistant) || typeof homeAssistant.configured !== 'boolean' || typeof homeAssistant.reachable !== 'boolean') {
    return false
  }

  if (!isRecord(mqtt) || typeof mqtt.configured !== 'boolean' || typeof mqtt.enabled !== 'boolean' || typeof mqtt.connected !== 'boolean') {
    return false
  }

  if (!isRecord(zwavejs) || typeof zwavejs.configured !== 'boolean' || typeof zwavejs.enabled !== 'boolean' || typeof zwavejs.connected !== 'boolean') {
    return false
  }

  if (!isRecord(zigbee2mqtt) || typeof zigbee2mqtt.enabled !== 'boolean') {
    return false
  }

  if (!isRecord(frigate) || typeof frigate.enabled !== 'boolean' || typeof frigate.available !== 'boolean') {
    return false
  }

  return true
}

// ============================================================================
// Form & Enum Guards
// ============================================================================

/**
 * Type for rule when operator (from RulesPage.tsx)
 */
export type WhenOperator = 'all' | 'any'

/**
 * Check if value is a valid WhenOperator
 */
export function isWhenOperator(value: unknown): value is WhenOperator {
  return value === 'all' || value === 'any'
}

/**
 * Type for alarm arm mode (from RulesPage.tsx)
 */
export type AlarmArmMode = 'armed_home' | 'armed_away' | 'armed_night' | 'armed_vacation'

/**
 * Check if value is a valid AlarmArmMode
 */
export function isAlarmArmMode(value: unknown): value is AlarmArmMode {
  return (
    value === 'armed_home' ||
    value === 'armed_away' ||
    value === 'armed_night' ||
    value === 'armed_vacation'
  )
}

/**
 * Countdown type values
 */
export type CountdownType = 'entry' | 'exit' | 'trigger'

/**
 * Check if value is a valid CountdownType
 */
export function isCountdownType(value: unknown): value is CountdownType {
  return value === 'entry' || value === 'exit' || value === 'trigger'
}

/**
 * Code type option (from CodesPage)
 */
export type CreateCodeTypeOption = 'permanent' | 'temporary'

/**
 * Check if value is a valid CreateCodeTypeOption
 */
export function isCreateCodeTypeOption(value: unknown): value is CreateCodeTypeOption {
  return value === 'permanent' || value === 'temporary'
}
