import { describe, expect, it } from 'vitest'
import type { Entity } from '@/types'
import { getZwavejsNodeId, isCodeCapableLock } from './lockFilters'

function makeEntity(overrides: Partial<Entity> = {}): Entity {
  return {
    id: 1,
    entityId: 'lock.test',
    domain: 'lock',
    name: 'Test Lock',
    deviceClass: null,
    lastState: null,
    lastChanged: null,
    lastSeen: null,
    attributes: {},
    source: 'home_assistant',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function makeZwaveLock(nodeId: unknown = 5): Entity {
  return makeEntity({
    source: 'zwavejs',
    attributes: { zwavejs: { node_id: nodeId, home_id: 123 } },
  })
}

describe('getZwavejsNodeId', () => {
  it('returns node_id from snake_case key', () => {
    expect(getZwavejsNodeId(makeZwaveLock(5))).toBe(5)
  })

  it('returns nodeId from camelCase key', () => {
    const entity = makeEntity({
      attributes: { zwavejs: { nodeId: 7 } },
    })
    expect(getZwavejsNodeId(entity)).toBe(7)
  })

  it('coerces numeric string node_id', () => {
    expect(getZwavejsNodeId(makeZwaveLock('12'))).toBe(12)
  })

  it('returns null for HA-only lock (no zwavejs attrs)', () => {
    expect(getZwavejsNodeId(makeEntity())).toBeNull()
  })

  it('returns null when zwavejs attr is not an object', () => {
    const entity = makeEntity({ attributes: { zwavejs: 'bad' } })
    expect(getZwavejsNodeId(entity)).toBeNull()
  })

  it('returns null for missing node_id', () => {
    const entity = makeEntity({ attributes: { zwavejs: { home_id: 123 } } })
    expect(getZwavejsNodeId(entity)).toBeNull()
  })

  it('returns null for null node_id', () => {
    expect(getZwavejsNodeId(makeZwaveLock(null))).toBeNull()
  })

  it('returns null for non-numeric string node_id', () => {
    expect(getZwavejsNodeId(makeZwaveLock('abc'))).toBeNull()
  })

  it('returns null for NaN node_id', () => {
    expect(getZwavejsNodeId(makeZwaveLock(NaN))).toBeNull()
  })

  it('returns null for Infinity node_id', () => {
    expect(getZwavejsNodeId(makeZwaveLock(Infinity))).toBeNull()
  })

  it('returns null when attributes is empty', () => {
    const entity = makeEntity({ attributes: {} })
    expect(getZwavejsNodeId(entity)).toBeNull()
  })
})

describe('isCodeCapableLock', () => {
  it('returns true for Z-Wave lock with node_id', () => {
    expect(isCodeCapableLock(makeZwaveLock(5))).toBe(true)
  })

  it('returns false for HA-only lock', () => {
    expect(isCodeCapableLock(makeEntity())).toBe(false)
  })

  it('returns false for zigbee lock', () => {
    const entity = makeEntity({
      source: 'zigbee2mqtt',
      attributes: { zigbee2mqtt: { ieee_address: '0x001' } },
    })
    expect(isCodeCapableLock(entity)).toBe(false)
  })

  it('returns false for non-lock domain even with zwavejs attrs', () => {
    const entity = makeZwaveLock(5)
    entity.domain = 'sensor'
    expect(isCodeCapableLock(entity)).toBe(false)
  })

  it('returns false for Z-Wave lock without node_id', () => {
    const entity = makeEntity({
      source: 'zwavejs',
      attributes: { zwavejs: {} },
    })
    expect(isCodeCapableLock(entity)).toBe(false)
  })
})
