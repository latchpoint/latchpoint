import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useFrigateSettingsModel } from '@/features/frigate/hooks/useFrigateSettingsModel'

const update = vi.fn().mockResolvedValue({ ok: true })
const statusRefetch = vi.fn().mockResolvedValue({ isError: false })
const settingsRefetch = vi.fn().mockResolvedValue({ isError: false })
const detectionsRefetch = vi.fn().mockResolvedValue({ isError: false })

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

vi.mock('@/hooks/useFrigate', () => {
  return {
    useFrigateStatusQuery: () => ({ data: { mqtt: { enabled: true, configured: true, connected: true } }, refetch: statusRefetch }),
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
      refetch: settingsRefetch,
    }),
    useUpdateFrigateSettingsMutation: () => ({ isPending: false, mutateAsync: update }),
    useFrigateDetectionsQuery: () => ({ data: [], refetch: detectionsRefetch }),
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

  it('AC-16: save/refresh through helper; reset stays info variant', async () => {
    update.mockReset().mockResolvedValue({ ok: true })
    statusRefetch.mockReset().mockResolvedValue({ isError: false })
    settingsRefetch.mockReset().mockResolvedValue({ isError: false })
    detectionsRefetch.mockReset().mockResolvedValue({ isError: false })

    const { result } = renderHook(() => useFrigateSettingsModel())
    await act(async () => {
      await Promise.resolve()
    })

    // save success → green notice
    await act(async () => {
      await result.current.save()
    })
    expect(result.current.noticeVariant).toBe('success')
    expect(result.current.notice).toMatch(/Saved Frigate/i)

    // save failure → categorized error
    update.mockRejectedValueOnce({ message: 'x', code: '400', details: { eventsTopic: ['required'] } })
    await act(async () => {
      await result.current.save()
    })
    expect(result.current.error).toMatch(/^Save failed/)
    expect(result.current.error).toMatch(/eventsTopic/)

    // refresh success
    await act(async () => {
      await result.current.refresh()
    })
    expect(result.current.noticeVariant).toBe('success')
    expect(result.current.notice).toMatch(/Refreshed Frigate/i)

    // refresh failure → Refresh-prefixed error.
    // TanStack Query's refetch() resolves with { isError, error } — it does
    // not reject — so mock that shape to exercise the helper's isError check.
    settingsRefetch.mockResolvedValueOnce({
      isError: true,
      error: new TypeError('Failed to fetch'),
    })
    await act(async () => {
      await result.current.refresh()
    })
    expect(result.current.error).toMatch(/^Refresh failed/)

    // reset regression — uses window.confirm; info variant, not 'success'
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    try {
      update.mockResolvedValueOnce({ ok: true })
      await act(async () => {
        result.current.reset()
        await Promise.resolve()
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(result.current.notice).toBe('Reset Frigate settings.')
      expect(result.current.noticeVariant).toBe('info')
    } finally {
      confirmSpy.mockRestore()
    }
  })
})
