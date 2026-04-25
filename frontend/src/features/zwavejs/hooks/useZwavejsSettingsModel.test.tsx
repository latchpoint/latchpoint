import { describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useZwavejsSettingsModel } from '@/features/zwavejs/hooks/useZwavejsSettingsModel'

vi.mock('@/hooks/useAuthQueries', () => {
  return { useCurrentUserQuery: () => ({ data: { role: 'admin' } }) }
})

const updateMutateAsync = vi.fn()
const syncMutateAsync = vi.fn()
const statusRefetch = vi.fn()
const settingsRefetch = vi.fn()

vi.mock('@/hooks/useZwavejs', () => {
  return {
    useZwavejsStatusQuery: () => ({ data: { enabled: true }, refetch: statusRefetch }),
    useZwavejsSettingsQuery: () => ({
      data: { enabled: false, wsUrl: '', connectTimeoutSeconds: 5, reconnectMinSeconds: 1, reconnectMaxSeconds: 30 },
      isLoading: false,
      refetch: settingsRefetch,
    }),
    useUpdateZwavejsSettingsMutation: () => ({ isPending: false, mutateAsync: updateMutateAsync }),
    useSyncZwavejsEntitiesMutation: () => ({ isPending: false, mutateAsync: syncMutateAsync }),
  }
})

describe('useZwavejsSettingsModel', () => {
  it('provides read-only draft from settings query', async () => {
    const { result } = renderHook(() => useZwavejsSettingsModel())

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.draft).toMatchObject({
      enabled: false,
      wsUrl: '',
      connectTimeoutSeconds: 5,
      reconnectMinSeconds: 1,
      reconnectMaxSeconds: 30,
    })
    expect(result.current.isAdmin).toBe(true)
  })

  it('AC-14: save/refresh route through helper; sync keeps info variant', async () => {
    updateMutateAsync.mockReset()
    syncMutateAsync.mockReset()
    statusRefetch.mockReset()
    settingsRefetch.mockReset()

    const { result } = renderHook(() => useZwavejsSettingsModel())
    await act(async () => {
      await Promise.resolve()
    })

    // save success → green notice
    updateMutateAsync.mockResolvedValueOnce(undefined)
    await act(async () => {
      await result.current.save()
    })
    expect(result.current.notice).toMatch(/Saved Z-Wave/i)
    expect(result.current.noticeVariant).toBe('success')

    // save failure → categorized error
    updateMutateAsync.mockRejectedValueOnce({ message: 'x', code: '400', details: { wsUrl: ['Invalid'] } })
    await act(async () => {
      await result.current.save()
    })
    expect(result.current.error).toMatch(/^Save failed/)
    expect(result.current.error).toMatch(/wsUrl/)

    // refresh success → green notice
    statusRefetch.mockResolvedValueOnce({ isError: false })
    settingsRefetch.mockResolvedValueOnce({ isError: false })
    await act(async () => {
      await result.current.refresh()
    })
    expect(result.current.noticeVariant).toBe('success')
    expect(result.current.notice).toMatch(/Refreshed Z-Wave/i)

    // refresh failure → Refresh-prefixed error.
    // TanStack Query's refetch() resolves with { isError, error } — it does
    // not reject — so mock that shape to exercise the helper's isError check.
    statusRefetch.mockResolvedValueOnce({
      isError: true,
      error: new TypeError('Failed to fetch'),
    })
    settingsRefetch.mockResolvedValueOnce({ isError: false })
    await act(async () => {
      await result.current.refresh()
    })
    expect(result.current.error).toMatch(/^Refresh failed/)

    // sync regression — success notice stays info-variant (not 'success')
    syncMutateAsync.mockResolvedValueOnce({ notice: 'Synced 3 entities.' })
    await act(async () => {
      await result.current.sync()
    })
    expect(result.current.notice).toBe('Synced 3 entities.')
    expect(result.current.noticeVariant).toBe('info')
  })
})
