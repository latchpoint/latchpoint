/**
 * Types for React Query Builder integration
 */
import type { RuleGroupType, RuleType, Field, OptionGroup } from 'react-querybuilder'

// Entity source filter used to scope entity pickers to a single integration.
export type EntitySource = 'home_assistant' | 'zwavejs' | 'zigbee2mqtt' | 'all'

// Minimal entity shape consumed by value editors. Kept separate from the
// wire-format Entity type so editors don't depend on unrelated fields.
export interface EntityOption {
  entityId: string
  name: string
  domain: string
  source?: string
}

export interface FrigateConfig {
  cameras: string[]
  zonesByCamera: Record<string, string[]>
}

// Shape of the object forwarded to value editors via QueryBuilder's `context`
// prop. Centralising this type lets every editor narrow `props.context`
// without scattered casts.
export interface ValueEditorContext {
  entities: EntityOption[]
  frigate?: FrigateConfig
}

// Field names that map to our condition operators. Source-specific
// `entity_state_*` variants are produced by converters.ts and registered as
// fields in RuleQueryBuilder.tsx, so they belong in the union.
export type ConditionFieldName =
  | 'alarm_state_in'
  | 'entity_state'
  | 'entity_state_ha'
  | 'entity_state_zwavejs'
  | 'entity_state_z2m'
  | 'frigate_person_detected'
  | 'time_in_range'

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

export interface TimeInRangeValue {
  start: string
  end: string
  days: string[] // mon..sun
  tz: string // 'system' or IANA id
}

// Extended rule type with our custom values
export interface AlarmRule extends Omit<RuleType, 'value'> {
  field: ConditionFieldName
  value: AlarmStateValue | EntityStateValue | FrigatePersonValue | TimeInRangeValue | unknown
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
