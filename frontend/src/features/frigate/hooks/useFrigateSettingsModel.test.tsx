import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useFrigateSettingsModel } from '@/features/frigate/hooks/useFrigateSettingsModel'

const update = vi.fn().mockResolvedValue({ ok: true })

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useFrigate', () => {
  return {
    useFrigateStatusQuery: () => ({ data: { mqtt: { enabled: true, configured: true, connected: true } }, refetch: vi.fn() }),
    useFrigateSettingsQuery: () => ({
      data: {
        enabled: false,
        eventsTopic: 'frigate/events',
        retentionSeconds: 3600,
        runRulesOnEvent: true,
        runRulesDebounceSeconds: 2,
        runRulesMaxPerMinute: 30,
        runRulesKinds: ['trigger'],
        knownCameras: [],
        knownZonesByCamera: {},
      },
      isLoading: false,
      refetch: vi.fn(),
    }),
    useUpdateFrigateSettingsMutation: () => ({ isPending: false, mutateAsync: update }),
    useFrigateDetectionsQuery: () => ({ data: [], refetch: vi.fn() }),
  }
})

describe('useFrigateSettingsModel', () => {
  it('tolerates invalid zones JSON by sending empty object', async () => {
    const { result } = renderHook(() => useFrigateSettingsModel())

    await act(async () => {
      await Promise.resolve()
    })

    act(() => {
      result.current.setDraft((prev) => (prev ? { ...prev, knownZonesByCameraJson: '{not json' } : prev))
    })

    await act(async () => {
      await result.current.save()
    })

    expect(update).toHaveBeenCalledWith(expect.objectContaining({ knownZonesByCamera: {} }))
  })
})

