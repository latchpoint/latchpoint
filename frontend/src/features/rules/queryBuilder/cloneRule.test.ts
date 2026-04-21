import { describe, expect, it } from 'vitest'
import { cloneRule, disambiguateCopyName } from './cloneRule'
import type { Rule } from '@/types/rules'

function makeRule(overrides: Partial<Rule> = {}): Rule {
  return {
    id: 42,
    name: 'Test Rule',
    kind: 'trigger',
    enabled: true,
    priority: 100,
    stopProcessing: false,
    stopGroup: '',
    schemaVersion: 1,
    definition: {
      when: {
        type: 'and',
        conditions: [{ type: 'entity_state', entity_id: 'binary_sensor.door', state: 'on' }],
      },
      then: [{ type: 'alarm_trigger' }],
    },
    cooldownSeconds: 30,
    entityIds: ['binary_sensor.door'],
    createdBy: null,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('disambiguateCopyName', () => {
  it('returns "(copy)" suffix when no collision', () => {
    expect(disambiguateCopyName('Arm Away', [])).toBe('Arm Away (copy)')
    expect(disambiguateCopyName('Arm Away', ['Other'])).toBe('Arm Away (copy)')
  })

  it('increments when "(copy)" already exists', () => {
    expect(disambiguateCopyName('Arm Away', ['Arm Away (copy)'])).toBe('Arm Away (copy 2)')
  })

  it('finds the next free slot when multiple copies exist', () => {
    const existing = ['Arm Away (copy)', 'Arm Away (copy 2)', 'Arm Away (copy 3)']
    expect(disambiguateCopyName('Arm Away', existing)).toBe('Arm Away (copy 4)')
  })

  it('skips over gaps to find the next occupied suffix', () => {
    const existing = ['Arm Away (copy)', 'Arm Away (copy 3)']
    expect(disambiguateCopyName('Arm Away', existing)).toBe('Arm Away (copy 2)')
  })
})

describe('cloneRule', () => {
  it('carries over all mutable fields', () => {
    const rule = makeRule()
    const seed = cloneRule(rule, [])

    expect(seed.kind).toBe(rule.kind)
    expect(seed.enabled).toBe(rule.enabled)
    expect(seed.priority).toBe(rule.priority)
    expect(seed.stopProcessing).toBe(rule.stopProcessing)
    expect(seed.stopGroup).toBe(rule.stopGroup)
    expect(seed.schemaVersion).toBe(rule.schemaVersion)
    expect(seed.cooldownSeconds).toBe(rule.cooldownSeconds)
    expect(seed.definition).toEqual(rule.definition)
  })

  it('suffixes the name and honors existing-name collisions', () => {
    const rule = makeRule({ name: 'Arm Away' })
    expect(cloneRule(rule, []).name).toBe('Arm Away (copy)')
    expect(cloneRule(rule, ['Arm Away (copy)']).name).toBe('Arm Away (copy 2)')
  })

  it('omits server-owned fields (no id, no timestamps, no entityIds)', () => {
    const rule = makeRule()
    const seed = cloneRule(rule, [])
    expect(seed).not.toHaveProperty('id')
    expect(seed).not.toHaveProperty('createdAt')
    expect(seed).not.toHaveProperty('updatedAt')
    expect(seed).not.toHaveProperty('createdBy')
    expect(seed).not.toHaveProperty('entityIds')
  })

  it('deep-clones definition so mutating the seed does not touch the source', () => {
    const rule = makeRule()
    const seed = cloneRule(rule, [])

    ;(seed.definition.then as any).push({ type: 'alarm_disarm' })
    const seedWhen = seed.definition.when as any
    if (seedWhen && 'conditions' in seedWhen) {
      seedWhen.conditions.push({ type: 'entity_state', entity_id: 'x', state: 'y' })
    }

    expect(rule.definition.then).toHaveLength(1)
    const ruleWhen = rule.definition.when as any
    expect(ruleWhen.conditions).toHaveLength(1)
  })
})
