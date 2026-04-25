import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useHomeAssistantSettingsModel } from '@/features/homeAssistant/hooks/useHomeAssistantSettingsModel'

const haUpdate = vi.fn()
const mqttEntityUpdate = vi.fn()
const publishDiscovery = vi.fn()
const haStatusRefetch = vi.fn().mockResolvedValue({ isError: false })
const haSettingsRefetch = vi.fn().mockResolvedValue({ isError: false })
const mqttEntityRefetch = vi.fn().mockResolvedValue({ isError: false })
const mqttEntityStatusRefetch = vi.fn().mockResolvedValue({ isError: false })

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useHomeAssistant', () => {
  return {
    useHomeAssistantStatus: () => ({ data: { configured: true, reachable: true }, refetch: haStatusRefetch }),
    useHomeAssistantSettingsQuery: () => ({
      data: { enabled: true, baseUrl: 'http://ha', connectTimeoutSeconds: 2, hasToken: true },
      refetch: haSettingsRefetch,
    }),
    useUpdateHomeAssistantSettingsMutation: () => ({ isPending: false, mutateAsync: haUpdate }),
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
    useHomeAssistantMqttAlarmEntitySettingsQuery: () => ({ data: { enabled: false }, refetch: mqttEntityRefetch }),
    useHomeAssistantMqttAlarmEntityStatusQuery: () => ({ data: { status: 'ok' }, refetch: mqttEntityStatusRefetch }),
    useUpdateHomeAssistantMqttAlarmEntitySettingsMutation: () => ({ isPending: false, mutateAsync: mqttEntityUpdate }),
    usePublishHomeAssistantMqttAlarmEntityDiscoveryMutation: () => ({ isPending: false, mutateAsync: publishDiscovery }),
  }
})

describe('useHomeAssistantSettingsModel', () => {
  it('provides read-only connection draft from settings query', async () => {
    const { result } = renderHook(() => useHomeAssistantSettingsModel())

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.connectionDraft).toMatchObject({
      enabled: true,
      baseUrl: 'http://ha',
      connectTimeoutSeconds: 2,
    })
    expect(result.current.maskedFlags).toMatchObject({ hasToken: true })
    expect(result.current.isAdmin).toBe(true)
    expect(result.current.mqttReady).toBe(true)
  })

  it('AC-17: save/refresh pairs through shared helper; publishDiscovery info regression', async () => {
    haUpdate.mockReset()
    mqttEntityUpdate.mockReset()
    publishDiscovery.mockReset()
    haStatusRefetch.mockReset().mockResolvedValue({ isError: false })
    haSettingsRefetch.mockReset().mockResolvedValue({ isError: false })
    mqttEntityRefetch.mockReset().mockResolvedValue({ isError: false })
    mqttEntityStatusRefetch.mockReset().mockResolvedValue({ isError: false })

    const { result } = renderHook(() => useHomeAssistantSettingsModel())
    await act(async () => {
      await Promise.resolve()
    })

    // saveConnection success
    haUpdate.mockResolvedValueOnce(undefined)
    await act(async () => {
      await result.current.saveConnection()
    })
    expect(result.current.noticeVariant).toBe('success')
    expect(result.current.notice).toMatch(/Home Assistant/i)

    // saveConnection failure
    haUpdate.mockRejectedValueOnce({ message: 'x', code: '500' })
    await act(async () => {
      await result.current.saveConnection()
    })
    expect(result.current.error).toMatch(/^Save failed/)

    // refreshConnection success
    await act(async () => {
      await result.current.refreshConnection()
    })
    expect(result.current.noticeVariant).toBe('success')

    // saveMqttEntity success shares same helper slot
    mqttEntityUpdate.mockResolvedValueOnce(undefined)
    await act(async () => {
      await result.current.saveMqttEntity()
    })
    expect(result.current.noticeVariant).toBe('success')
    expect(result.current.notice).toMatch(/Home Assistant MQTT/i)

    // refreshMqttEntity failure.
    // TanStack Query's refetch() resolves with { isError, error } — it does
    // not reject — so mock that shape to exercise the helper's isError check.
    mqttEntityRefetch.mockResolvedValueOnce({
      isError: true,
      error: new TypeError('Failed to fetch'),
    })
    await act(async () => {
      await result.current.refreshMqttEntity()
    })
    expect(result.current.error).toMatch(/^Refresh failed/)

    // publishDiscovery regression: info variant, not 'success'
    publishDiscovery.mockResolvedValueOnce(undefined)
    await act(async () => {
      await result.current.publishDiscovery()
    })
    expect(result.current.notice).toMatch(/Published Home Assistant/i)
    expect(result.current.noticeVariant).toBe('info')
  })
})
