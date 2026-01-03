/**
 * Types for React Query Builder integration
 */
import type { RuleGroupType, RuleType, Field, OptionGroup } from 'react-querybuilder'

// Field names that map to our condition operators
export type ConditionFieldName = 'alarm_state_in' | 'entity_state' | 'frigate_person_detected'

// Custom rule value types
export interface AlarmStateValue {
  states: string[]
}

export interface EntityStateValue {
  entityId: string
  equals: string
}

export interface FrigatePersonValue {
  cameras: string[]
  zones: string[]
  withinSeconds: number
  minConfidencePct: number
  aggregation: 'max' | 'latest' | 'percentile'
  percentile?: number
  onUnavailable: 'treat_as_match' | 'treat_as_no_match'
}

// Extended rule type with our custom values
export interface AlarmRule extends Omit<RuleType, 'value'> {
  field: ConditionFieldName
  value: AlarmStateValue | EntityStateValue | FrigatePersonValue | unknown
}

export interface AlarmRuleGroup extends Omit<RuleGroupType, 'rules'> {
  rules: (AlarmRule | AlarmRuleGroup)[]
}

// Field definition with typed values
export interface AlarmField extends Field {
  name: ConditionFieldName
  inputType?: string
  values?: OptionGroup[]
}

// Alarm states available in the system
export const ALARM_STATES = [
  { name: 'disarmed', label: 'Disarmed' },
  { name: 'arming', label: 'Arming' },
  { name: 'armed_home', label: 'Armed Home' },
  { name: 'armed_away', label: 'Armed Away' },
  { name: 'armed_night', label: 'Armed Night' },
  { name: 'armed_vacation', label: 'Armed Vacation' },
  { name: 'pending', label: 'Pending' },
  { name: 'triggered', label: 'Triggered' },
] as const

export type AlarmStateName = (typeof ALARM_STATES)[number]['name']
