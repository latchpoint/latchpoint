import type { Rule } from '@/types'
import { parseRuleDefinition } from '@/types/ruleDefinition'
import { isAlarmArmMode, isRecord, isWhenOperator } from '@/lib/typeGuards'
import { uniqueId, uniqueStrings, type ActionRow, type ConditionRow, type WhenOperator } from '@/features/rules/builder'

export function hydrateBuilderFromRule(rule: Rule): {
  whenOperator: WhenOperator
  forSecondsText: string
  conditions: ConditionRow[]
  actions: ActionRow[]
} | null {
  const parsedDef = parseRuleDefinition(rule.definition)
  if (!parsedDef) return null

  const asObj = parsedDef

  const nextConditions: ConditionRow[] = []
  const addCondition = (node: unknown, negate = false) => {
    if (!isRecord(node)) return
    if (node.op === 'entity_state' && typeof node.entity_id === 'string') {
      nextConditions.push({
        id: uniqueId(),
        type: 'entity_state',
        entityId: node.entity_id,
        equals: typeof node.equals === 'string' ? node.equals : 'on',
        negate,
      })
      return
    }
    if (node.op === 'alarm_state_in') {
      const states = Array.isArray(node.states) ? node.states.map(String) : []
      nextConditions.push({
        id: uniqueId(),
        type: 'alarm_state_in',
        negate,
        states: uniqueStrings(states),
      })
      return
    }
    if (node.op === 'frigate_person_detected') {
      const cameras = Array.isArray(node.cameras) ? node.cameras.map(String) : []
      const zones = Array.isArray(node.zones) ? node.zones.map(String) : []
      nextConditions.push({
        id: uniqueId(),
        type: 'frigate_person_detected',
        negate,
        cameras: uniqueStrings(cameras),
        zones: uniqueStrings(zones),
        withinSeconds: typeof node.within_seconds === 'number' ? String(node.within_seconds) : '10',
        minConfidencePct: typeof node.min_confidence_pct === 'number' ? String(node.min_confidence_pct) : '90',
        aggregation: node.aggregation === 'latest' || node.aggregation === 'percentile' || node.aggregation === 'max' ? node.aggregation : 'max',
        percentile: typeof node.percentile === 'number' ? String(node.percentile) : '90',
        onUnavailable: node.on_unavailable === 'treat_as_match' || node.on_unavailable === 'treat_as_no_match' ? node.on_unavailable : 'treat_as_no_match',
      })
    }
  }

  let baseWhen: unknown = asObj.when
  let forSecondsText = ''
  if (isRecord(baseWhen) && baseWhen.op === 'for' && typeof baseWhen.seconds === 'number') {
    forSecondsText = String(baseWhen.seconds)
    baseWhen = baseWhen.child
  }

  let whenOperator: WhenOperator = 'all'
  if (isRecord(baseWhen) && isWhenOperator(baseWhen.op) && Array.isArray(baseWhen.children)) {
    whenOperator = baseWhen.op
    for (const child of baseWhen.children) {
      if (isRecord(child) && child.op === 'not') {
        addCondition(child.child, true)
      } else {
        addCondition(child, false)
      }
    }
  }

  const conditions = nextConditions.length
    ? nextConditions
    : [{ id: uniqueId(), type: 'entity_state' as const, entityId: '', equals: 'on', negate: false }]

  const nextActions: ActionRow[] = []
  if (Array.isArray(asObj.then)) {
    for (const action of asObj.then) {
      if (!isRecord(action)) continue
      const type = action.type
      if (type === 'alarm_disarm') nextActions.push({ id: uniqueId(), type: 'alarm_disarm' })
      if (type === 'alarm_trigger') nextActions.push({ id: uniqueId(), type: 'alarm_trigger' })
      if (type === 'alarm_arm' && typeof action.mode === 'string' && isAlarmArmMode(action.mode)) {
        nextActions.push({ id: uniqueId(), type: 'alarm_arm', mode: action.mode })
      }
      if (type === 'ha_call_service') {
        const target = isRecord(action.target) ? action.target : null
        const targetEntityIds = Array.isArray(target?.entity_ids) ? target.entity_ids.map(String).join(', ') : ''
        // Parse action field (e.g., "notify.notify") into domain and service
        const actionStr = typeof action.action === 'string' ? action.action : ''
        const dotIndex = actionStr.indexOf('.')
        const domain = dotIndex > 0 ? actionStr.slice(0, dotIndex) : ''
        const service = dotIndex > 0 ? actionStr.slice(dotIndex + 1) : ''
        nextActions.push({
          id: uniqueId(),
          type: 'ha_call_service',
          domain,
          service,
          targetEntityIds,
          serviceDataJson: JSON.stringify(action.data ?? {}, null, 2),
        })
      }
      if (type === 'zwavejs_set_value') {
        const valueId = isRecord(action.value_id) ? action.value_id : null
        nextActions.push({
          id: uniqueId(),
          type: 'zwavejs_set_value',
          nodeId: typeof action.node_id === 'number' ? String(action.node_id) : '',
          commandClass: typeof valueId?.commandClass === 'number' ? String(valueId.commandClass) : '',
          endpoint: typeof valueId?.endpoint === 'number' ? String(valueId.endpoint) : '0',
          property: typeof valueId?.property === 'number' ? String(valueId.property) : typeof valueId?.property === 'string' ? valueId.property : '',
          propertyKey:
            typeof valueId?.propertyKey === 'number' ? String(valueId.propertyKey) : typeof valueId?.propertyKey === 'string' ? valueId.propertyKey : '',
          valueJson: JSON.stringify(action.value ?? null, null, 2),
        })
      }
      if (type === 'zigbee2mqtt_set_value') {
        nextActions.push({
          id: uniqueId(),
          type: 'zigbee2mqtt_set_value',
          entityId: typeof action.entity_id === 'string' ? action.entity_id : '',
          valueJson: JSON.stringify(action.value ?? null, null, 2),
        })
      }
      if (type === 'zigbee2mqtt_switch') {
        nextActions.push({
          id: uniqueId(),
          type: 'zigbee2mqtt_switch',
          entityId: typeof action.entity_id === 'string' ? action.entity_id : '',
          state: action.state === 'off' ? 'off' : 'on',
        })
      }
      if (type === 'zigbee2mqtt_light') {
        nextActions.push({
          id: uniqueId(),
          type: 'zigbee2mqtt_light',
          entityId: typeof action.entity_id === 'string' ? action.entity_id : '',
          state: action.state === 'off' ? 'off' : 'on',
          brightness: typeof action.brightness === 'number' ? String(action.brightness) : '',
        })
      }
      if (type === 'send_notification') {
        nextActions.push({
          id: uniqueId(),
          type: 'send_notification',
          providerId: typeof action.provider_id === 'string' ? action.provider_id : '',
          message: typeof action.message === 'string' ? action.message : '',
          title: typeof action.title === 'string' ? action.title : '',
          dataJson: JSON.stringify(action.data ?? {}, null, 2),
        })
      }
    }
  }

  return { whenOperator, forSecondsText, conditions, actions: nextActions.length ? nextActions : [{ id: uniqueId(), type: 'alarm_trigger' }] }
}
