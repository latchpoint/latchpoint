import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useMqttSettingsModel } from '@/features/mqtt/hooks/useMqttSettingsModel'

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useMqtt', () => {
  return {
    useMqttStatusQuery: () => ({ data: { enabled: true }, refetch: vi.fn() }),
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
      refetch: vi.fn(),
    }),
    useUpdateMqttSettingsMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({}) }),
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
      port: '1883',
      username: '',
      clientId: 'latchpoint-alarm',
      hasPassword: false,
    })
    expect(result.current.isAdmin).toBe(true)
    expect(result.current.error).toBeNull()
    expect(result.current.notice).toBeNull()
  })
})
