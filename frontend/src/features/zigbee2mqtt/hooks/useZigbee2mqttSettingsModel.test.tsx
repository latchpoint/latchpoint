import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useZigbee2mqttSettingsModel } from '@/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel'

const update = vi.fn().mockResolvedValue({ ok: true })
const statusRefetch = vi.fn().mockResolvedValue({})
const settingsRefetch = vi.fn().mockResolvedValue({})
const devicesRefetch = vi.fn().mockResolvedValue({})

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useZigbee2mqtt', () => {
  return {
    useZigbee2mqttStatusQuery: () => ({ data: { enabled: true, connected: true, mqtt: { enabled: true, configured: true, connected: true }, sync: {} }, isLoading: false, refetch: statusRefetch }),
    useZigbee2mqttSettingsQuery: () => ({ data: { enabled: false, baseTopic: 'zigbee2mqtt', runRulesKinds: ['trigger'] }, isLoading: false, refetch: settingsRefetch }),
    useZigbee2mqttDevicesQuery: () => ({ data: [], isLoading: false, refetch: devicesRefetch }),
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

  it('AC-15: save/refresh route through helper', async () => {
    update.mockReset()
    statusRefetch.mockReset().mockResolvedValue({})
    settingsRefetch.mockReset().mockResolvedValue({})
    devicesRefetch.mockReset().mockResolvedValue({})

    const { result } = renderHook(() => useZigbee2mqttSettingsModel())
    await act(async () => {
      await Promise.resolve()
    })

    // save success → green notice
    update.mockResolvedValueOnce({ ok: true })
    await act(async () => {
      await result.current.save()
    })
    expect(result.current.noticeVariant).toBe('success')
    expect(result.current.notice).toMatch(/Saved Zigbee2MQTT/i)

    // save failure → categorized error
    update.mockRejectedValueOnce({ message: 'x', code: '500' })
    await act(async () => {
      await result.current.save()
    })
    expect(result.current.error).toMatch(/^Save failed/)

    // refresh success
    await act(async () => {
      await result.current.refresh()
    })
    expect(result.current.noticeVariant).toBe('success')
    expect(result.current.notice).toMatch(/Refreshed Zigbee2MQTT/i)

    // refresh failure
    settingsRefetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await act(async () => {
      await result.current.refresh()
    })
    expect(result.current.error).toMatch(/^Refresh failed/)
  })
})
