import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useMqttSettingsModel } from '@/features/mqtt/hooks/useMqttSettingsModel'

const updateMqtt = vi.fn().mockResolvedValue({ ok: true })
const testMqtt = vi.fn().mockResolvedValue({ ok: true })

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
    useUpdateMqttSettingsMutation: () => ({ isPending: false, mutateAsync: updateMqtt }),
    useTestMqttConnectionMutation: () => ({ isPending: false, mutateAsync: testMqtt }),
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
    useUpdateHomeAssistantMqttAlarmEntitySettingsMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
  }
})

describe('useMqttSettingsModel', () => {
  it('requires host when enabled', async () => {
    const { result } = renderHook(() => useMqttSettingsModel())

    await act(async () => {
      await Promise.resolve()
    })

    act(() => {
      result.current.setDraft((prev) =>
        prev
          ? { ...prev, enabled: true, host: '' }
          : prev
      )
    })

    await act(async () => {
      await result.current.save()
    })

    expect(result.current.error).toBe('Broker host is required when MQTT is enabled.')
    expect(updateMqtt).not.toHaveBeenCalled()
  })

  it('clears password via mutation and updates draft', async () => {
    const { result } = renderHook(() => useMqttSettingsModel())

    await act(async () => {
      await Promise.resolve()
    })

    act(() => {
      result.current.setDraft((prev) =>
        prev
          ? { ...prev, hasPassword: true, password: 'x' }
          : prev
      )
    })

    await act(async () => {
      await result.current.clearPassword()
    })

    expect(updateMqtt).toHaveBeenCalledWith({ password: '' })
    expect(result.current.notice).toBe('Cleared MQTT password.')
  })
})

