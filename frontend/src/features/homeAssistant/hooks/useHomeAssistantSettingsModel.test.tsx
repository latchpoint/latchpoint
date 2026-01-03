import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useHomeAssistantSettingsModel } from '@/features/homeAssistant/hooks/useHomeAssistantSettingsModel'

const updateHa = vi.fn().mockResolvedValue({ ok: true })

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
    useUpdateHomeAssistantSettingsMutation: () => ({ isPending: false, mutateAsync: updateHa }),
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
  it('clearToken disables and clears token', async () => {
    const { result } = renderHook(() => useHomeAssistantSettingsModel())

    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      await result.current.clearToken()
    })

    expect(updateHa).toHaveBeenCalledWith({ enabled: false, token: '' })
    expect(result.current.notice).toMatch(/cleared home assistant token/i)
  })
})

