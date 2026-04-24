import { describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useMqttSettingsModel } from '@/features/mqtt/hooks/useMqttSettingsModel'

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

const mutateAsyncMock = vi.fn()
const statusRefetchMock = vi.fn()
const settingsRefetchMock = vi.fn()

vi.mock('@/hooks/useMqtt', () => {
  return {
    useMqttStatusQuery: () => ({ data: { enabled: true }, refetch: statusRefetchMock }),
    useUpdateMqttSettingsMutation: () => ({ isPending: false, mutateAsync: mutateAsyncMock }),
    useMqttSettingsQuery: () => ({
      data: {
        enabled: false,
        host: '',
        port: 1883,
        username: '',
        useTls: false,
        tlsInsecure: false,
        clientId: 'latchpoint-alarm',
        keepaliveSeconds: 30,
        connectTimeoutSeconds: 5,
        hasPassword: false,
      },
      isLoading: false,
      refetch: settingsRefetchMock,
    }),
  }
})

vi.mock('@/hooks/useZigbee2mqtt', () => {
  return { useZigbee2mqttSettingsQuery: () => ({ data: null }) }
})

vi.mock('@/hooks/useFrigate', () => {
  return { useFrigateSettingsQuery: () => ({ data: null }) }
})

vi.mock('@/hooks/useHomeAssistantMqttAlarmEntity', () => {
  return {
    useHomeAssistantMqttAlarmEntitySettingsQuery: () => ({ data: { enabled: false }, refetch: vi.fn() }),
  }
})

describe('useMqttSettingsModel', () => {
  it('provides read-only draft from settings query', async () => {
    const { result } = renderHook(() => useMqttSettingsModel())

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.draft).toMatchObject({
      enabled: false,
      host: '',
      port: 1883,
      username: '',
      clientId: 'latchpoint-alarm',
    })
    expect(result.current.maskedFlags).toMatchObject({ hasPassword: false })
    expect(result.current.isAdmin).toBe(true)
    expect(result.current.error).toBeNull()
    expect(result.current.notice).toBeNull()
  })

  it('AC-13: save/refresh route through useSettingsActionFeedback', async () => {
    mutateAsyncMock.mockReset()
    statusRefetchMock.mockReset()
    settingsRefetchMock.mockReset()

    const { result } = renderHook(() => useMqttSettingsModel())
    await act(async () => {
      await Promise.resolve()
    })

    // save success → green notice
    mutateAsyncMock.mockResolvedValueOnce(undefined)
    await act(async () => {
      await result.current.save()
    })
    expect(result.current.notice).toMatch(/Saved MQTT settings/i)
    expect(result.current.noticeVariant).toBe('success')
    expect(result.current.error).toBeNull()

    // save failure → categorized red error
    mutateAsyncMock.mockRejectedValueOnce({ message: 'nope', code: '403' })
    await act(async () => {
      await result.current.save()
    })
    expect(result.current.error).toBe(
      "Save failed: you don't have permission to change these settings."
    )
    expect(result.current.notice).toBeNull()

    // refresh success → green notice
    statusRefetchMock.mockResolvedValueOnce({})
    settingsRefetchMock.mockResolvedValueOnce({})
    await act(async () => {
      await result.current.refresh()
    })
    expect(result.current.notice).toMatch(/Refreshed MQTT/i)
    expect(result.current.noticeVariant).toBe('success')
    expect(result.current.error).toBeNull()

    // refresh failure → categorized red error (Refresh prefix)
    statusRefetchMock.mockRejectedValueOnce({ message: 'nope', code: '500' })
    settingsRefetchMock.mockResolvedValueOnce({})
    await act(async () => {
      await result.current.refresh()
    })
    expect(result.current.error).toMatch(/^Refresh failed/)
  })
})
