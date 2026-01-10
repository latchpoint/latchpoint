/**
 * Type definitions and guards for rule definitions
 * Provides type-safe handling of rule when/then structures
 */

import { isRecord } from '@/lib/typeGuards'
import type { WhenOperator, AlarmArmMode } from '@/lib/typeGuards'

// ============================================================================
// When Condition Nodes
// ============================================================================

/**
 * Base entity state condition
 */
export interface EntityStateNode {
  op: 'entity_state'
  entity_id: string
  equals: string
  /**
   * UI hint for which entity-source dropdown was selected when the rule was authored.
   * This is also used server-side to help backfill `Entity.source` when a referenced entity
   * is created via rule refs before an integration sync has populated it.
   */
  source?: 'home_assistant' | 'zwavejs' | 'zigbee2mqtt' | 'all'
}

export type FrigateAggregation = 'latest' | 'max' | 'percentile'
export type FrigateOnUnavailable = 'treat_as_match' | 'treat_as_no_match'

export interface FrigatePersonDetectedNode {
  op: 'frigate_person_detected'
  cameras: string[]
  zones?: string[]
  within_seconds: number
  min_confidence_pct: number
  aggregation?: FrigateAggregation
  percentile?: number
  on_unavailable?: FrigateOnUnavailable
}

export interface AlarmStateInNode {
  op: 'alarm_state_in'
  states: string[]
}

/**
 * Negation wrapper
 */
export interface NotNode {
  op: 'not'
  child: ConditionNode
}

/**
 * Logical operator node (all/any)
 */
export interface LogicalNode {
  op: WhenOperator
  children: ConditionNode[]
}

/**
 * For duration wrapper
 */
export interface ForNode {
  op: 'for'
  seconds: number
  child: WhenNode
}

/**
 * Union of all condition node types
 */
export type ConditionNode = EntityStateNode | FrigatePersonDetectedNode | AlarmStateInNode | NotNode

/**
 * Union of all when node types
 */
export type WhenNode = EntityStateNode | LogicalNode | ForNode | Record<string, never>

// ============================================================================
// Action Nodes
// ============================================================================

/**
 * Alarm disarm action
 */
export interface AlarmDisarmAction {
  type: 'alarm_disarm'
}

/**
 * Alarm trigger action
 */
export interface AlarmTriggerAction {
  type: 'alarm_trigger'
}

/**
 * Alarm arm action
 */
export interface AlarmArmAction {
  type: 'alarm_arm'
  mode: AlarmArmMode
}

/**
 * Home Assistant call service action
 * Uses "action" field in domain.service format (e.g., "notify.notify")
 * to match Home Assistant 2024.8+ terminology and backend schema
 */
export interface HaCallServiceAction {
  type: 'ha_call_service'
  action: string
  target?: {
    entity_ids: string[]
  }
  data?: Record<string, unknown>
}

export interface ZwavejsSetValueAction {
  type: 'zwavejs_set_value'
  node_id: number
  value_id: {
    commandClass: number
    endpoint?: number
    property: string | number
    propertyKey?: string | number
  }
  value: unknown
}

export interface Zigbee2mqttSetValueAction {
  type: 'zigbee2mqtt_set_value'
  entity_id: string
  value: unknown
}

export interface Zigbee2mqttSwitchAction {
  type: 'zigbee2mqtt_switch'
  entity_id: string
  state: 'on' | 'off'
}

export interface Zigbee2mqttLightAction {
  type: 'zigbee2mqtt_light'
  entity_id: string
  state: 'on' | 'off'
  brightness?: number
}

/**
 * Send notification action using notification providers
 */
export interface SendNotificationAction {
  type: 'send_notification'
  provider_id: string
  message: string
  title?: string
  data?: Record<string, unknown>
}

/**
 * Union of all action types
 */
export type ActionNode =
  | AlarmDisarmAction
  | AlarmTriggerAction
  | AlarmArmAction
  | HaCallServiceAction
  | ZwavejsSetValueAction
  | Zigbee2mqttSetValueAction
  | Zigbee2mqttSwitchAction
  | Zigbee2mqttLightAction
  | SendNotificationAction

// ============================================================================
// Rule Definition
// ============================================================================

/**
 * Complete rule definition structure
 */
export interface RuleDefinition {
  when: WhenNode
  then: ActionNode[]
}

// ============================================================================
// Type Guards
// ============================================================================

/**
 * Check if node is an EntityStateNode
 */
export function isEntityStateNode(node: unknown): node is EntityStateNode {
  return (
    isRecord(node) &&
    node.op === 'entity_state' &&
    typeof node.entity_id === 'string' &&
    typeof node.equals === 'string'
  )
}

export function isFrigatePersonDetectedNode(node: unknown): node is FrigatePersonDetectedNode {
  if (!isRecord(node)) return false
  if (node.op !== 'frigate_person_detected') return false
  if (!Array.isArray(node.cameras) || !node.cameras.every((c) => typeof c === 'string')) return false
  if (typeof node.within_seconds !== 'number') return false
  if (typeof node.min_confidence_pct !== 'number') return false
  if ('zones' in node && node.zones != null) {
    if (!Array.isArray(node.zones) || !node.zones.every((z) => typeof z === 'string')) return false
  }
  if ('aggregation' in node && node.aggregation != null) {
    if (node.aggregation !== 'latest' && node.aggregation !== 'max' && node.aggregation !== 'percentile') return false
  }
  if ('percentile' in node && node.percentile != null && typeof node.percentile !== 'number') return false
  if ('on_unavailable' in node && node.on_unavailable != null) {
    if (node.on_unavailable !== 'treat_as_match' && node.on_unavailable !== 'treat_as_no_match') return false
  }
  return true
}

/**
 * Check if node is a NotNode
 */
export function isNotNode(node: unknown): node is NotNode {
  return isRecord(node) && node.op === 'not' && isConditionNode(node.child)
}

/**
 * Check if node is a ConditionNode
 */
export function isConditionNode(node: unknown): node is ConditionNode {
  return isEntityStateNode(node) || isFrigatePersonDetectedNode(node) || isAlarmStateInNode(node) || isNotNode(node)
}

/**
 * Check if node is a LogicalNode
 */
export function isLogicalNode(node: unknown): node is LogicalNode {
  if (!isRecord(node)) return false
  if (node.op !== 'all' && node.op !== 'any') return false
  if (!Array.isArray(node.children)) return false
  return node.children.every(isConditionNode)
}

/**
 * Check if node is a ForNode
 */
export function isForNode(node: unknown): node is ForNode {
  return (
    isRecord(node) &&
    node.op === 'for' &&
    typeof node.seconds === 'number' &&
    isWhenNode(node.child)
  )
}

/**
 * Check if node is a valid WhenNode
 */
export function isWhenNode(node: unknown): node is WhenNode {
  // Empty when node
  if (isRecord(node) && Object.keys(node).length === 0) return true

  return isConditionNode(node) || isLogicalNode(node) || isForNode(node)
}

export function isAlarmStateInNode(node: unknown): node is AlarmStateInNode {
  if (!isRecord(node)) return false
  if (node.op !== 'alarm_state_in') return false
  if (!Array.isArray(node.states) || !node.states.every((s) => typeof s === 'string')) return false
  return true
}

/**
 * Check if action is AlarmDisarmAction
 */
export function isAlarmDisarmAction(action: unknown): action is AlarmDisarmAction {
  return isRecord(action) && action.type === 'alarm_disarm'
}

/**
 * Check if action is AlarmTriggerAction
 */
export function isAlarmTriggerAction(action: unknown): action is AlarmTriggerAction {
  return isRecord(action) && action.type === 'alarm_trigger'
}

/**
 * Check if action is AlarmArmAction
 */
export function isAlarmArmAction(action: unknown): action is AlarmArmAction {
  return (
    isRecord(action) &&
    action.type === 'alarm_arm' &&
    typeof action.mode === 'string' &&
    ['armed_home', 'armed_away', 'armed_night', 'armed_vacation'].includes(action.mode as string)
  )
}

/**
 * Check if action is HaCallServiceAction
 * Validates the "action" field is in domain.service format (e.g., "notify.notify")
 */
export function isHaCallServiceAction(action: unknown): action is HaCallServiceAction {
  if (!isRecord(action)) return false
  if (action.type !== 'ha_call_service') return false
  if (typeof action.action !== 'string') return false
  // Validate action is in domain.service format
  if (!action.action.includes('.')) return false

  // target and data are optional
  if ('target' in action) {
    const target = action.target
    if (!isRecord(target)) return false
    if ('entity_ids' in target && !Array.isArray(target.entity_ids)) return false
  }

  if ('data' in action && !isRecord(action.data)) return false

  return true
}

export function isZwavejsSetValueAction(action: unknown): action is ZwavejsSetValueAction {
  if (!isRecord(action)) return false
  if (action.type !== 'zwavejs_set_value') return false
  if (typeof action.node_id !== 'number') return false
  const valueId = action.value_id
  if (!isRecord(valueId)) return false
  if (typeof valueId.commandClass !== 'number') return false
  if ('endpoint' in valueId && typeof valueId.endpoint !== 'number') return false
  if (!('property' in valueId)) return false
  const prop = valueId.property
  if (!(typeof prop === 'string' || typeof prop === 'number')) return false
  if ('propertyKey' in valueId && !(typeof valueId.propertyKey === 'string' || typeof valueId.propertyKey === 'number')) return false
  return true
}

export function isZigbee2mqttSetValueAction(action: unknown): action is Zigbee2mqttSetValueAction {
  if (!isRecord(action)) return false
  if (action.type !== 'zigbee2mqtt_set_value') return false
  if (typeof action.entity_id !== 'string' || action.entity_id.trim() === '') return false
  if (!('value' in action)) return false
  return true
}

export function isZigbee2mqttSwitchAction(action: unknown): action is Zigbee2mqttSwitchAction {
  if (!isRecord(action)) return false
  if (action.type !== 'zigbee2mqtt_switch') return false
  if (typeof action.entity_id !== 'string' || action.entity_id.trim() === '') return false
  if (action.state !== 'on' && action.state !== 'off') return false
  return true
}

export function isZigbee2mqttLightAction(action: unknown): action is Zigbee2mqttLightAction {
  if (!isRecord(action)) return false
  if (action.type !== 'zigbee2mqtt_light') return false
  if (typeof action.entity_id !== 'string' || action.entity_id.trim() === '') return false
  if (action.state !== 'on' && action.state !== 'off') return false
  if ('brightness' in action && action.brightness !== undefined && typeof action.brightness !== 'number') return false
  return true
}

/**
 * Check if action is SendNotificationAction
 */
export function isSendNotificationAction(action: unknown): action is SendNotificationAction {
  if (!isRecord(action)) return false
  if (action.type !== 'send_notification') return false
  if (typeof action.provider_id !== 'string') return false
  if (typeof action.message !== 'string') return false
  if ('title' in action && action.title !== undefined && typeof action.title !== 'string') return false
  if ('data' in action && action.data !== undefined && !isRecord(action.data)) return false
  return true
}

/**
 * Check if action is a valid ActionNode
 */
export function isActionNode(action: unknown): action is ActionNode {
  return (
    isAlarmDisarmAction(action) ||
    isAlarmTriggerAction(action) ||
    isAlarmArmAction(action) ||
    isHaCallServiceAction(action) ||
    isZwavejsSetValueAction(action) ||
    isZigbee2mqttSetValueAction(action) ||
    isZigbee2mqttSwitchAction(action) ||
    isZigbee2mqttLightAction(action) ||
    isSendNotificationAction(action)
  )
}

/**
 * Check if value is a valid RuleDefinition
 */
export function isRuleDefinition(data: unknown): data is RuleDefinition {
  if (!isRecord(data)) return false
  if (!('when' in data) || !('then' in data)) return false

  const { when, then } = data

  // Validate when node
  if (!isWhenNode(when)) return false

  // Validate then actions
  if (!Array.isArray(then)) return false
  if (!then.every(isActionNode)) return false

  return true
}

/**
 * Parse and validate rule definition from unknown data
 * Returns the validated definition or undefined if invalid
 */
export function parseRuleDefinition(data: unknown): RuleDefinition | undefined {
  return isRuleDefinition(data) ? data : undefined
}

/**
 * Create an empty rule definition
 */
export function createEmptyRuleDefinition(): RuleDefinition {
  return {
    when: {},
    then: [],
  }
}
