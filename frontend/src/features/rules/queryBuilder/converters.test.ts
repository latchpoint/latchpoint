import { describe, expect, it } from 'vitest'
import type { RuleGroupType } from 'react-querybuilder'
import { alarmDslToRqbWithFor, rqbToAlarmDsl } from './converters'

describe('converters', () => {
  it('imports', async () => {
    const mod = await import('./converters')
    expect(mod).toBeTruthy()
  })

  it('persists selected entity source dropdown (HA)', () => {
    const query: RuleGroupType = {
      id: 'g1',
      combinator: 'and',
      rules: [
        {
          id: 'r1',
          field: 'entity_state_ha',
          operator: '=',
          value: { entityId: 'binary_sensor.front_door', equals: 'on' },
        },
      ],
    }

    const when = rqbToAlarmDsl(query)
    expect(JSON.stringify(when)).toContain('"source":"home_assistant"')

    const roundTrip = alarmDslToRqbWithFor(when)
    const rule = roundTrip.query.rules[0] as any
    expect(rule.field).toBe('entity_state_ha')
  })

  it('persists selected entity source dropdown (All Sources)', () => {
    const query: RuleGroupType = {
      id: 'g1',
      combinator: 'and',
      rules: [
        {
          id: 'r1',
          field: 'entity_state',
          operator: '=',
          value: { entityId: 'binary_sensor.front_door', equals: 'on' },
        },
      ],
    }

    const when = rqbToAlarmDsl(query)
    expect(JSON.stringify(when)).toContain('"source":"all"')

    const roundTrip = alarmDslToRqbWithFor(when)
    const rule = roundTrip.query.rules[0] as any
    expect(rule.field).toBe('entity_state')
  })

  it('round-trips nested groups with entity_state children', () => {
    const when = {
      op: 'all',
      children: [
        {
          op: 'alarm_state_in',
          states: ['armed_home', 'armed_away', 'armed_night', 'armed_vacation'],
        },
        {
          op: 'all',
          children: [
            {
              op: 'entity_state',
              equals: 'on',
              source: 'home_assistant',
              entity_id: 'binary_sensor.back_door_window_door_is_open',
            },
            {
              op: 'entity_state',
              equals: 'on',
              source: 'home_assistant',
              entity_id: 'binary_sensor.front_door_window_door_is_open',
            },
          ],
        },
      ],
    } as any

    const result = alarmDslToRqbWithFor(when)
    expect(result.query.rules).toHaveLength(2)

    const nestedGroup = result.query.rules[1] as any
    expect(nestedGroup.combinator).toBe('and')
    expect(nestedGroup.rules).toHaveLength(2)
    expect(nestedGroup.rules[0].field).toBe('entity_state_ha')
    expect(nestedGroup.rules[1].field).toBe('entity_state_ha')

    const roundTripWhen = rqbToAlarmDsl(result.query)
    const json = JSON.stringify(roundTripWhen)
    expect(json).toContain('binary_sensor.back_door_window_door_is_open')
    expect(json).toContain('binary_sensor.front_door_window_door_is_open')
  })

  it('handles API-camelCased entityId in stored definitions', () => {
    const when = {
      op: 'all',
      children: [
        {
          op: 'entity_state',
          equals: 'on',
          source: 'home_assistant',
          entityId: 'binary_sensor.front_door_window_door_is_open',
        },
      ],
    } as any

    const result = alarmDslToRqbWithFor(when)
    const rule = result.query.rules[0] as any
    expect(rule.field).toBe('entity_state_ha')
    expect(rule.value.entityId).toBe('binary_sensor.front_door_window_door_is_open')
  })
})
