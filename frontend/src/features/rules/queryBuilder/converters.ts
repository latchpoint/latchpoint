/**
 * Converters between React Query Builder format and our alarm DSL
 */
import type { RuleGroupType, RuleType } from 'react-querybuilder'
import type {
  WhenNode,
  LogicalNode,
  EntityStateNode,
  AlarmStateInNode,
  FrigatePersonDetectedNode,
  NotNode,
  ConditionNode,
  ForNode,
} from '@/types/ruleDefinition'
import type { AlarmStateValue, EntityStateValue, FrigatePersonValue } from './types'

/**
 * Generate a unique ID for RQB rules
 */
function generateId(): string {
  return `r-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

/**
 * Result of converting alarm DSL to RQB format
 * Includes the query and optional forSeconds extracted from ForNode
 */
export interface AlarmDslToRqbResult {
  query: RuleGroupType
  forSeconds: number | null
}

/**
 * Entity info for source lookup during conversion
 */
interface EntityInfo {
  entityId: string
  source?: string
}

/**
 * Convert our alarm DSL WhenNode to React Query Builder format
 * Returns both the query and any "for" duration wrapper
 */
export function alarmDslToRqb(when: WhenNode, entities?: EntityInfo[]): RuleGroupType {
  const result = alarmDslToRqbWithFor(when, entities)
  return result.query
}

/**
 * Convert alarm DSL to RQB format, extracting ForNode if present
 * @param when - The WhenNode from the rule definition
 * @param entities - Optional list of entities for source lookup
 */
export function alarmDslToRqbWithFor(when: WhenNode, entities?: EntityInfo[]): AlarmDslToRqbResult {
  // Handle empty when node
  if (!when || Object.keys(when).length === 0) {
    return {
      query: {
        id: generateId(),
        combinator: 'and',
        rules: [],
      },
      forSeconds: null,
    }
  }

  // Handle ForNode wrapper - extract seconds and recurse on child
  if ('op' in when && when.op === 'for') {
    const forNode = when as ForNode
    const childResult = alarmDslToRqbWithFor(forNode.child, entities)
    return {
      query: childResult.query,
      forSeconds: forNode.seconds,
    }
  }

  // Handle logical nodes (all/any)
  if ('op' in when && (when.op === 'all' || when.op === 'any')) {
    const logicalNode = when as LogicalNode
    return {
      query: {
        id: generateId(),
        combinator: logicalNode.op === 'all' ? 'and' : 'or',
        rules: logicalNode.children.map((child) => conditionNodeToRqbRule(child, entities)),
      },
      forSeconds: null,
    }
  }

  // Handle single condition (wrap in a group)
  if ('op' in when) {
    const rule = conditionNodeToRqbRule(when as ConditionNode, entities)
    return {
      query: {
        id: generateId(),
        combinator: 'and',
        rules: [rule],
      },
      forSeconds: null,
    }
  }

  // Fallback: empty group
  return {
    query: {
      id: generateId(),
      combinator: 'and',
      rules: [],
    },
    forSeconds: null,
  }
}

/**
 * Map entity source to RQB field name
 */
function sourceToFieldName(source?: string): string {
  switch (source) {
    case 'home_assistant':
      return 'entity_state_ha'
    case 'zwavejs':
      return 'entity_state_zwavejs'
    case 'zigbee2mqtt':
      return 'entity_state_z2m'
    case 'all':
      return 'entity_state'
    default:
      return 'entity_state'
  }
}

function fieldNameToSource(field?: string): string | undefined {
  switch (field) {
    case 'entity_state':
      return 'all'
    case 'entity_state_ha':
      return 'home_assistant'
    case 'entity_state_zwavejs':
      return 'zwavejs'
    case 'entity_state_z2m':
      return 'zigbee2mqtt'
    default:
      return undefined
  }
}

/**
 * Convert a single condition node to an RQB rule or group
 * Handles nested logical groups (all/any) by returning RuleGroupType
 * @param node - The condition node to convert (can be a nested LogicalNode at runtime)
 * @param entities - Optional list of entities for source lookup
 */
function conditionNodeToRqbRule(node: ConditionNode | LogicalNode, entities?: EntityInfo[]): RuleType | RuleGroupType {
  // Handle nested logical groups (all/any)
  if ('children' in node && (node.op === 'all' || node.op === 'any')) {
    const logicalNode = node as LogicalNode
    return {
      id: generateId(),
      combinator: logicalNode.op === 'all' ? 'and' : 'or',
      rules: logicalNode.children.map((child) => conditionNodeToRqbRule(child, entities)),
    }
  }

  // Handle NOT wrapper
  if (node.op === 'not') {
    const notNode = node as NotNode
    const innerRule = conditionNodeToRqbRule(notNode.child as ConditionNode, entities)
    // Only negate if it's a simple rule, not a group
    if ('field' in innerRule) {
      return {
        ...innerRule,
        operator: innerRule.operator === '=' ? '!=' : innerRule.operator,
      }
    }
    // For negated groups, just return the group (RQB doesn't support NOT on groups directly)
    return innerRule
  }

  // Handle entity_state
  if (node.op === 'entity_state') {
    const esNode = node as EntityStateNode & {
      // API client camel-cases response keys; support both shapes on read.
      entityId?: string
    }
    const entityId = (esNode.entity_id || esNode.entityId || '').trim()
    const equals = (esNode.equals || '').trim()
    const value: EntityStateValue = {
      entityId,
      equals,
    }
    // Prefer explicitly saved rule source (preserves UI dropdown selection),
    // otherwise fall back to entity registry lookup.
    const savedSource = typeof esNode.source === 'string' ? esNode.source : undefined
    const entity = entities?.find((e) => e.entityId === entityId)
    const field = sourceToFieldName(savedSource || entity?.source)
    return {
      id: generateId(),
      field,
      operator: '=',
      value,
    }
  }

  // Handle alarm_state_in
  if (node.op === 'alarm_state_in') {
    const asNode = node as AlarmStateInNode & {
      // API client camel-cases response keys; support both shapes on read.
      states?: string[]
    }
    const value: AlarmStateValue = {
      states: asNode.states,
    }
    return {
      id: generateId(),
      field: 'alarm_state_in',
      operator: 'in',
      value,
    }
  }

  // Handle frigate_person_detected
  if (node.op === 'frigate_person_detected') {
    const fpNode = node as FrigatePersonDetectedNode & {
      // API client camel-cases response keys; support both shapes on read.
      withinSeconds?: number
      minConfidencePct?: number
      onUnavailable?: string
    }
    const value: FrigatePersonValue = {
      cameras: fpNode.cameras,
      zones: fpNode.zones || [],
      withinSeconds: fpNode.within_seconds ?? fpNode.withinSeconds,
      minConfidencePct: fpNode.min_confidence_pct ?? fpNode.minConfidencePct,
      aggregation: fpNode.aggregation || 'max',
      percentile: fpNode.percentile,
      onUnavailable: (fpNode.on_unavailable || fpNode.onUnavailable) as any || 'treat_as_no_match',
    }
    return {
      id: generateId(),
      field: 'frigate_person_detected',
      operator: 'detected',
      value,
    }
  }

  // Fallback: unknown condition type
  return {
    id: generateId(),
    field: 'entity_state',
    operator: '=',
    value: { entityId: '', equals: '' },
  }
}

/**
 * Convert React Query Builder format to our alarm DSL WhenNode
 */
export function rqbToAlarmDsl(query: RuleGroupType, forSeconds?: number | null): WhenNode {
  const children = query.rules
    .map((rule) => {
      if ('combinator' in rule) {
        // Nested group - recursively convert (don't pass forSeconds to nested groups)
        const nestedWhen = rqbToAlarmDsl(rule as RuleGroupType)
        if ('op' in nestedWhen) {
          return nestedWhen as ConditionNode
        }
        return null
      }

      // Single rule
      return rqbRuleToConditionNode(rule as RuleType)
    })
    .filter((node): node is ConditionNode => node !== null)

  // If no children, return empty when
  if (children.length === 0) {
    return {}
  }

  // Build the base logical node
  let baseNode: WhenNode

  // If only one child, wrap it in a logical node anyway for consistency
  // This ensures the when node is always a LogicalNode with children
  // (The backend supports both single conditions and logical groups)
  if (children.length === 1) {
    // Wrap single child in 'all' for consistency with backend expectations
    baseNode = {
      op: 'all',
      children,
    } as LogicalNode
  } else {
    // Multiple children: wrap in logical operator
    const op = query.combinator === 'or' ? 'any' : 'all'
    baseNode = {
      op,
      children,
    } as LogicalNode
  }

  // Wrap in ForNode if forSeconds is provided
  if (forSeconds != null && forSeconds > 0) {
    return {
      op: 'for',
      seconds: forSeconds,
      child: baseNode,
    } as ForNode
  }

  return baseNode
}

/**
 * Convert a single RQB rule to a condition node
 */
function rqbRuleToConditionNode(rule: RuleType): ConditionNode | null {
  const { field, operator, value } = rule
  const isNegated = operator === '!='

  // Handle entity_state (all source-specific fields: entity_state_ha, entity_state_zwavejs, entity_state_z2m)
  if (field === 'entity_state' || field?.startsWith('entity_state_')) {
    const esValue = value as EntityStateValue
    if (!esValue?.entityId?.trim()) return null

    const baseNode: EntityStateNode = {
      op: 'entity_state',
      entity_id: esValue.entityId.trim(),
      equals: esValue.equals?.trim() || 'on',
      source: fieldNameToSource(field) as EntityStateNode['source'],
    }

    if (isNegated) {
      return { op: 'not', child: baseNode }
    }
    return baseNode
  }

  // Handle alarm_state_in
  if (field === 'alarm_state_in') {
    const asValue = value as AlarmStateValue
    if (!asValue?.states?.length) return null

    const baseNode: AlarmStateInNode = {
      op: 'alarm_state_in',
      states: asValue.states,
    }

    if (isNegated) {
      return { op: 'not', child: baseNode }
    }
    return baseNode
  }

  // Handle frigate_person_detected
  if (field === 'frigate_person_detected') {
    const fpValue = value as FrigatePersonValue
    if (!fpValue?.cameras?.length) return null

    const baseNode: FrigatePersonDetectedNode = {
      op: 'frigate_person_detected',
      cameras: fpValue.cameras,
      zones: fpValue.zones?.length ? fpValue.zones : undefined,
      within_seconds: fpValue.withinSeconds || 10,
      min_confidence_pct: fpValue.minConfidencePct || 85,
      aggregation: fpValue.aggregation || 'max',
      percentile: fpValue.aggregation === 'percentile' ? fpValue.percentile : undefined,
      on_unavailable: fpValue.onUnavailable || 'treat_as_no_match',
    }

    if (isNegated) {
      return { op: 'not', child: baseNode }
    }
    return baseNode
  }

  return null
}

/**
 * Create a default empty query for initialization
 */
export function createEmptyQuery(): RuleGroupType {
  return {
    id: generateId(),
    combinator: 'and',
    rules: [],
  }
}

/**
 * Create a default rule for a given field
 */
export function createDefaultRule(field: string): RuleType {
  const id = generateId()

  switch (field) {
    case 'alarm_state_in':
      return {
        id,
        field: 'alarm_state_in',
        operator: 'in',
        value: { states: ['armed_home', 'armed_away'] } as AlarmStateValue,
      }

    case 'entity_state':
    case 'entity_state_ha':
    case 'entity_state_zwavejs':
    case 'entity_state_z2m':
      return {
        id,
        field,
        operator: '=',
        value: { entityId: '', equals: 'on' } as EntityStateValue,
      }

    case 'frigate_person_detected':
      return {
        id,
        field: 'frigate_person_detected',
        operator: 'detected',
        value: {
          cameras: [],
          zones: [],
          withinSeconds: 10,
          minConfidencePct: 85,
          aggregation: 'max',
          onUnavailable: 'treat_as_no_match',
        } as FrigatePersonValue,
      }

    default:
      return {
        id,
        field: 'entity_state_ha',
        operator: '=',
        value: { entityId: '', equals: 'on' } as EntityStateValue,
      }
  }
}
