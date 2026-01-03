import { isRecord, type AlarmArmMode, type WhenOperator } from '@/lib/typeGuards'

export type { AlarmArmMode, WhenOperator } from '@/lib/typeGuards'

export type EntityStateConditionRow = {
  id: string
  type: 'entity_state'
  entityId: string
  equals: string
  negate: boolean
}

export type FrigatePersonConditionRow = {
  id: string
  type: 'frigate_person_detected'
  negate: boolean
  cameras: string[]
  zones: string[]
  withinSeconds: string
  minConfidencePct: string
  aggregation: 'max' | 'latest' | 'percentile'
  percentile: string
  onUnavailable: 'treat_as_match' | 'treat_as_no_match'
}

export type AlarmStateConditionRow = {
  id: string
  type: 'alarm_state_in'
  negate: boolean
  states: string[]
}

export type ConditionRow = EntityStateConditionRow | FrigatePersonConditionRow | AlarmStateConditionRow

export const alarmStateOptions = [
  'disarmed',
  'arming',
  'armed_home',
  'armed_away',
  'armed_night',
  'armed_vacation',
  'pending',
  'triggered',
] as const

export type ActionRow =
  | { id: string; type: 'alarm_disarm' }
  | { id: string; type: 'alarm_trigger' }
  | { id: string; type: 'alarm_arm'; mode: AlarmArmMode }
  | {
      id: string
      type: 'ha_call_service'
      domain: string
      service: string
      targetEntityIds: string
      serviceDataJson: string
    }
  | {
      id: string
      type: 'zwavejs_set_value'
      nodeId: string
      commandClass: string
      endpoint: string
      property: string
      propertyKey: string
      valueJson: string
    }
  | {
      id: string
      type: 'zigbee2mqtt_set_value'
      entityId: string
      valueJson: string
    }
  | {
      id: string
      type: 'zigbee2mqtt_switch'
      entityId: string
      state: 'on' | 'off'
    }
  | {
      id: string
      type: 'zigbee2mqtt_light'
      entityId: string
      state: 'on' | 'off'
      brightness: string
    }
  | {
      id: string
      type: 'send_notification'
      providerId: string
      message: string
      title: string
      dataJson: string
    }

export function parseEntityIds(value: string): string[] {
  return value
    .split(/[\n,]+/g)
    .map((s) => s.trim())
    .filter(Boolean)
}

export function uniqueId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((v) => v.trim()).filter(Boolean)))
}

export function countThenActions(definition: unknown): number {
  if (!isRecord(definition)) return 0
  const thenValue = definition.then
  return Array.isArray(thenValue) ? thenValue.length : 0
}

export function buildDefinitionFromBuilder(
  whenOperator: WhenOperator,
  conditions: ConditionRow[],
  forSeconds: number | null,
  actions: ActionRow[]
): Record<string, unknown> {
  const conditionNodes: unknown[] = conditions
    .map((c) => {
      if (c.type === 'entity_state') {
        if (!c.entityId.trim() || !c.equals.trim()) return null
        const base = { op: 'entity_state', entity_id: c.entityId.trim(), equals: c.equals.trim() }
        if (c.negate) return { op: 'not', child: base }
        return base
      }

      if (c.type === 'alarm_state_in') {
        const states = uniqueStrings(c.states)
        if (!states.length) return null
        const base = { op: 'alarm_state_in', states }
        if (c.negate) return { op: 'not', child: base }
        return base
      }

      const cameras = uniqueStrings(c.cameras)
      const zones = uniqueStrings(c.zones)
      if (!cameras.length) return null
      const withinSeconds = Number.parseInt(c.withinSeconds.trim(), 10)
      const minConfidencePct = Number.parseFloat(c.minConfidencePct.trim())
      if (!Number.isFinite(withinSeconds) || withinSeconds <= 0) return null
      if (!Number.isFinite(minConfidencePct) || minConfidencePct < 0 || minConfidencePct > 100) return null
      const aggregation = c.aggregation || 'max'
      const base: Record<string, unknown> = {
        op: 'frigate_person_detected',
        cameras,
        ...(zones.length ? { zones } : {}),
        within_seconds: withinSeconds,
        min_confidence_pct: minConfidencePct,
        aggregation,
        on_unavailable: c.onUnavailable,
      }
      if (aggregation === 'percentile') {
        const percentile = Number.parseInt(c.percentile.trim(), 10)
        if (!Number.isFinite(percentile) || percentile <= 0 || percentile > 100) return null
        base.percentile = percentile
      }
      if (c.negate) return { op: 'not', child: base }
      return base
    })
    .filter(Boolean)

  const whenBase: Record<string, unknown> = conditionNodes.length === 0 ? {} : { op: whenOperator, children: conditionNodes }

  const when = forSeconds && forSeconds > 0 ? { op: 'for', seconds: forSeconds, child: whenBase } : whenBase

  const then: unknown[] = actions.map((a) => {
    if (a.type === 'alarm_disarm') return { type: 'alarm_disarm' }
    if (a.type === 'alarm_trigger') return { type: 'alarm_trigger' }
    if (a.type === 'alarm_arm') return { type: 'alarm_arm', mode: a.mode }
    if (a.type === 'send_notification') {
      const data = (() => {
        try {
          const parsed = JSON.parse(a.dataJson || '{}')
          return parsed && typeof parsed === 'object' ? parsed : undefined
        } catch {
          return undefined
        }
      })()
      return {
        type: 'send_notification',
        provider_id: a.providerId,
        message: a.message,
        ...(a.title ? { title: a.title } : {}),
        ...(data ? { data } : {}),
      }
    }
    if (a.type === 'zwavejs_set_value') {
      const nodeId = Number.parseInt(a.nodeId.trim() || '', 10)
      const commandClass = Number.parseInt(a.commandClass.trim() || '', 10)
      const endpoint = Number.parseInt(a.endpoint.trim() || '0', 10)
      const property = (() => {
        const raw = a.property.trim()
        const asNumber = Number.parseInt(raw, 10)
        return raw !== '' && String(asNumber) === raw ? asNumber : raw
      })()
      const propertyKey = (() => {
        const raw = a.propertyKey.trim()
        if (!raw) return undefined
        const asNumber = Number.parseInt(raw, 10)
        return String(asNumber) === raw ? asNumber : raw
      })()
      const value = (() => {
        try {
          return JSON.parse(a.valueJson || 'null')
        } catch {
          return a.valueJson
        }
      })()
      return {
        type: 'zwavejs_set_value',
        node_id: Number.isFinite(nodeId) ? nodeId : 0,
        value_id: {
          commandClass: Number.isFinite(commandClass) ? commandClass : 0,
          endpoint: Number.isFinite(endpoint) ? endpoint : 0,
          property,
          ...(propertyKey !== undefined ? { propertyKey } : {}),
        },
        value,
      }
    }
    if (a.type === 'zigbee2mqtt_set_value') {
      const entityId = a.entityId.trim()
      const value = (() => {
        try {
          return JSON.parse(a.valueJson || 'null')
        } catch {
          return a.valueJson
        }
      })()
      return {
        type: 'zigbee2mqtt_set_value',
        entity_id: entityId,
        value,
      }
    }
    if (a.type === 'zigbee2mqtt_switch') {
      const entityId = a.entityId.trim()
      return {
        type: 'zigbee2mqtt_switch',
        entity_id: entityId,
        state: a.state,
      }
    }
    if (a.type === 'zigbee2mqtt_light') {
      const entityId = a.entityId.trim()
      const brightnessParsed = a.brightness.trim() === '' ? null : Number.parseInt(a.brightness.trim(), 10)
      return {
        type: 'zigbee2mqtt_light',
        entity_id: entityId,
        state: a.state,
        ...(Number.isFinite(brightnessParsed) ? { brightness: brightnessParsed } : {}),
      }
    }
    // Combine domain.service into single action field per HA 2024.8+ terminology
    return {
      type: 'ha_call_service',
      action: `${a.domain.trim()}.${a.service.trim()}`,
      target: { entity_ids: parseEntityIds(a.targetEntityIds) },
      data: (() => {
        try {
          const parsed = JSON.parse(a.serviceDataJson || '{}')
          return parsed && typeof parsed === 'object' ? parsed : {}
        } catch {
          return {}
        }
      })(),
    }
  })

  return { when, then }
}
