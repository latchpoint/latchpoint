import { describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useZigbee2mqttSettingsModel } from '@/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel'

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useZigbee2mqtt', () => {
  return {
    useZigbee2mqttStatusQuery: () => ({ data: { enabled: true, connected: true, mqtt: { enabled: true, configured: true, connected: true }, sync: {} }, isLoading: false, refetch: vi.fn() }),
    useZigbee2mqttSettingsQuery: () => ({ data: { enabled: true, baseTopic: 'zigbee2mqtt', runRulesOnEvent: false, runRulesKinds: [] }, isLoading: false, refetch: vi.fn() }),
    useZigbee2mqttDevicesQuery: () => ({ data: [], isLoading: false, refetch: vi.fn() }),
    useSyncZigbee2mqttDevicesMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ devices: 0, entitiesUpserted: 0 }) }),
  }
})

describe('useZigbee2mqttSettingsModel', () => {
  it('returns read-only settings from query data', () => {
    const { result } = renderHook(() => useZigbee2mqttSettingsModel())

    expect(result.current.settings).toEqual({
      enabled: true,
      baseTopic: 'zigbee2mqtt',
      runRulesOnEvent: false,
      runRulesKinds: [],
    })
    expect(result.current.isAdmin).toBe(true)
    expect(result.current.z2mEnabled).toBe(true)
  })
})
