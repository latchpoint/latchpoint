import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useZigbee2mqttSettingsModel } from '@/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel'

const update = vi.fn().mockResolvedValue({ ok: true })

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useZigbee2mqtt', () => {
  return {
    useZigbee2mqttStatusQuery: () => ({ data: { enabled: true, connected: true, mqtt: { enabled: true, configured: true, connected: true }, sync: {} }, isLoading: false, refetch: vi.fn() }),
    useZigbee2mqttSettingsQuery: () => ({ data: { enabled: false, baseTopic: 'zigbee2mqtt', runRulesKinds: ['trigger'] }, isLoading: false, refetch: vi.fn() }),
    useZigbee2mqttDevicesQuery: () => ({ data: [], isLoading: false, refetch: vi.fn() }),
    useUpdateZigbee2mqttSettingsMutation: () => ({ isPending: false, mutateAsync: update }),
    useSyncZigbee2mqttDevicesMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({ devices: 0, entitiesUpserted: 0 }) }),
  }
})

describe('useZigbee2mqttSettingsModel', () => {
  it('splits runRulesKindsCsv into list on save', async () => {
    const { result } = renderHook(() => useZigbee2mqttSettingsModel())

    act(() => {
      result.current.updateDraft({ runRulesKindsCsv: 'trigger, disarm ,  ' })
    })

    await act(async () => {
      await result.current.save()
    })

    expect(update).toHaveBeenCalledWith(
      expect.objectContaining({
        runRulesKinds: ['trigger', 'disarm'],
      })
    )
  })
})

