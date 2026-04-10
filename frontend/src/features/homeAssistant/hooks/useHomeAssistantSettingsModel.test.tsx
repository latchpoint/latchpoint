import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useHomeAssistantSettingsModel } from '@/features/homeAssistant/hooks/useHomeAssistantSettingsModel'

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useHomeAssistant', () => {
  return {
    useHomeAssistantStatus: () => ({ data: { configured: true, reachable: true }, refetch: vi.fn() }),
    useHomeAssistantSettingsQuery: () => ({
      data: { enabled: true, baseUrl: 'http://ha', connectTimeoutSeconds: 2, hasToken: true },
      refetch: vi.fn(),
    }),
    useUpdateHomeAssistantSettingsMutation: () => ({ isPending: false, mutateAsync: vi.fn().mockResolvedValue({}) }),
  }
})

vi.mock('@/hooks/useMqtt', () => {
  return {
    useMqttStatusQuery: () => ({ data: { enabled: true } }),
    useMqttSettingsQuery: () => ({ data: { host: 'broker' } }),
  }
})

vi.mock('@/hooks/useHomeAssistantMqttAlarmEntity', () => {
  return {
    useHomeAssistantMqttAlarmEntitySettingsQuery: () => ({ data: { enabled: false } }),
    useHomeAssistantMqttAlarmEntityStatusQuery: () => ({ data: { status: 'ok' } }),
    useUpdateHomeAssistantMqttAlarmEntitySettingsMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    usePublishHomeAssistantMqttAlarmEntityDiscoveryMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
  }
})

describe('useHomeAssistantSettingsModel', () => {
  it('provides read-only connection draft from settings query', async () => {
    const { result } = renderHook(() => useHomeAssistantSettingsModel())

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.haConnectionDraft).toMatchObject({
      enabled: true,
      baseUrl: 'http://ha',
      hasToken: true,
      connectTimeoutSeconds: '2',
    })
    expect(result.current.isAdmin).toBe(true)
    expect(result.current.mqttReady).toBe(true)
  })
})
