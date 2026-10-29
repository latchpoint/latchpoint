import { createElement, type PropsWithChildren } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { queryKeys } from '@/types'
import type { DoorCode } from '@/types'
import {
  DOOR_CODES_SETTLING_POLL_MS,
  isDoorCodeSettling,
  useDeleteDoorCodeMutation,
  useDoorCodesQuery,
  useReadCachedDoorCode,
  useRetryDoorCodePushMutation,
} from './useDoorCodesQueries'

function createClient(queries: { staleTime?: number; refetchOnWindowFocus?: boolean } = {}) {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, ...queries }, mutations: { retry: false } },
  })
}

function makeCode(overrides: Partial<DoorCode> = {}): DoorCode {
  return {
    id: 7,
    userId: 'user-1',
    userDisplayName: 'Test',
    source: 'manual',
    label: 'Front',
    codeType: 'permanent',
    pin: null,
    pinLength: 4,
    isActive: true,
    maxUses: null,
    usesCount: 0,
    startAt: null,
    endAt: null,
    daysOfWeek: null,
    windowStart: null,
    windowEnd: null,
    lastUsedAt: null,
    lastUsedLock: null,
    lockAssignments: [{ id: 1, lockEntityId: 'lock.front_door' }],
    lockEntityIds: ['lock.front_door'],
    lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 3, pendingRemoval: false }],
    pendingSlotClears: [],
    validity: 'valid',
    pushState: 'pushed',
    lastPushError: '',
    lastPushAttemptAt: null,
    createdAt: '',
    updatedAt: '',
    ...overrides,
  }
}

// An active code the scheduler is still pushing, its lock has no slot yet.
const pendingPush = (overrides: Partial<DoorCode> = {}) =>
  makeCode({
    pushState: 'pending',
    lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: null, pendingRemoval: false }],
    ...overrides,
  })

// Serves state.codes from the codes endpoint and counts the fetches.
function serveCodes(initial: DoorCode[]) {
  const state = { codes: initial, fetches: 0 }
  server.use(
    http.get('/api/door-codes/', () => {
      state.fetches += 1
      return HttpResponse.json({ data: state.codes })
    }),
  )
  return state
}

function wrap(client: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return createElement(QueryClientProvider, { client }, children)
  }
}

describe('useDoorCodesQueries', () => {
  it('imports', async () => {
    const mod = await import('./useDoorCodesQueries')
    expect(mod).toBeTruthy()
  })

  it('rejects Retry with the API message and still refetches the codes', async () => {
    server.use(
      http.post('/api/door-codes/7/push/', () =>
        HttpResponse.json(
          {
            error: {
              status: 'conflict',
              message: 'Door code is inactive. Turn it on before pushing it to its locks.',
            },
          },
          { status: 409 },
        ),
      ),
    )

    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useRetryDoorCodePushMutation('user-1'), { wrapper: wrap(client) })

    await expect(result.current.mutateAsync(7)).rejects.toMatchObject({
      message: 'Door code is inactive. Turn it on before pushing it to its locks.',
      code: '409',
    })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.doorCodes.byUser('user-1') })
  })

  it('rejects a refused delete with the API message and still refetches the codes', async () => {
    const message =
      "Couldn't clear slot 3 on lock.front_door, it may still hold the PIN. The door code wasn't deleted and is now off, try again when the lock responds."
    server.use(
      http.delete('/api/door-codes/7/', () =>
        HttpResponse.json({ error: { status: 'gateway_error', message, gateway: 'zwavejs' } }, { status: 502 }),
      ),
    )

    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useDeleteDoorCodeMutation('user-1'), { wrapper: wrap(client) })

    await expect(result.current.mutateAsync({ id: 7, reauthPassword: 'pw' })).rejects.toMatchObject({
      message,
      code: '502',
    })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.doorCodes.byUser('user-1') })
  })

  it('refetches the codes after a delete that works', async () => {
    server.use(http.delete('/api/door-codes/7/', () => new HttpResponse(null, { status: 204 })))

    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useDeleteDoorCodeMutation('user-1'), { wrapper: wrap(client) })

    await result.current.mutateAsync({ id: 7, reauthPassword: 'pw' })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.doorCodes.byUser('user-1') })
  })

  it('reads a door code and when it was fetched from the cache', () => {
    const client = createClient()
    const code = { id: 7, userId: 'someone-else' } as DoorCode
    client.setQueryData(queryKeys.doorCodes.byUser('user-1'), [code], { updatedAt: 1234 })
    const { result } = renderHook(() => useReadCachedDoorCode('user-1'), { wrapper: wrap(client) })

    expect(result.current(7)).toEqual({ code, dataUpdatedAt: 1234 })
    expect(result.current(8)).toBeNull()
  })

  it('reads nothing when the codes for that user are not cached', () => {
    const client = createClient()
    const { result } = renderHook(() => useReadCachedDoorCode('user-1'), { wrapper: wrap(client) })

    expect(result.current(7)).toBeNull()
  })

  it('refetches the codes after a successful Retry', async () => {
    server.use(http.post('/api/door-codes/7/push/', () => HttpResponse.json({ data: { id: 7 } })))

    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useRetryDoorCodePushMutation('user-1'), { wrapper: wrap(client) })

    await result.current.mutateAsync(7)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.doorCodes.byUser('user-1') })
  })

  describe('isDoorCodeSettling', () => {
    it('is settling while an active code waits for a slot on one of its locks', () => {
      expect(isDoorCodeSettling(pendingPush())).toBe(true)
    })

    it('is settled for a pending code lock sync created, since the scheduler never pushes it', () => {
      expect(isDoorCodeSettling(makeCode({ source: 'synced', pushState: 'pending' }))).toBe(false)
    })

    it('is settled for an active pending code with no locks', () => {
      expect(
        isDoorCodeSettling(
          makeCode({ pushState: 'pending', lockAssignments: [], lockEntityIds: [], lockSlotAssignments: [] }),
        ),
      ).toBe(false)
    })

    it('is settled for an inactive pending code with nothing to clear', () => {
      expect(isDoorCodeSettling(pendingPush({ isActive: false }))).toBe(false)
    })

    it('is settling while a slot is left to clear', () => {
      const clear = { lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }
      expect(isDoorCodeSettling(makeCode({ isActive: false, pendingSlotClears: [clear] }))).toBe(true)
    })

    it('is settling while a lock is waiting on its removal', () => {
      const removing = [{ lockEntityId: 'lock.front_door', slotIndex: 3, pendingRemoval: true }]
      expect(isDoorCodeSettling(makeCode({ lockSlotAssignments: removing }))).toBe(true)
    })

    it('is settled once pushed with nothing to clear', () => {
      expect(isDoorCodeSettling(makeCode())).toBe(false)
    })

    it('is settled once failed, even with a clear left, since only a Retry moves it', () => {
      const clear = { lockEntityId: 'lock.front_door', slotIndex: 3, removing: true }
      expect(isDoorCodeSettling(makeCode({ pushState: 'failed', pendingSlotClears: [clear] }))).toBe(false)
    })
  })

  describe('useDoorCodesQuery', () => {
    afterEach(() => {
      vi.useRealTimers()
    })

    const renderCodes = (client = createClient()) =>
      renderHook(() => useDoorCodesQuery({ userId: 'user-1', isAdmin: true }), { wrapper: wrap(client) })

    it('polls while a code is pending and stops once it settles', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const served = serveCodes([pendingPush()])
      const { result } = renderCodes()
      await waitFor(() => expect(result.current.data?.[0].pushState).toBe('pending'))
      expect(served.fetches).toBe(1)

      await act(() => vi.advanceTimersByTimeAsync(DOOR_CODES_SETTLING_POLL_MS))
      await waitFor(() => expect(served.fetches).toBe(2))

      // The scheduler pushes it, and the next poll picks that up.
      served.codes = [makeCode()]
      await act(() => vi.advanceTimersByTimeAsync(DOOR_CODES_SETTLING_POLL_MS))
      await waitFor(() => expect(result.current.data?.[0].pushState).toBe('pushed'))
      expect(served.fetches).toBe(3)

      // Nothing is settling now, so it stops.
      await act(() => vi.advanceTimersByTimeAsync(DOOR_CODES_SETTLING_POLL_MS * 4))
      expect(served.fetches).toBe(3)
    })

    it("doesn't poll when nothing is settling", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const served = serveCodes([
        makeCode(),
        makeCode({ id: 8, pushState: 'failed', lastPushError: 'Lock timed out' }),
        makeCode({ id: 9, source: 'synced', pushState: 'pending' }),
        makeCode({ id: 10, pushState: 'pending', lockAssignments: [], lockEntityIds: [], lockSlotAssignments: [] }),
      ])
      const { result } = renderCodes()
      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      await act(() => vi.advanceTimersByTimeAsync(DOOR_CODES_SETTLING_POLL_MS * 4))
      expect(served.fetches).toBe(1)
    })

    it('refetches when the tab becomes visible again, even while the codes are fresh', async () => {
      const served = serveCodes([makeCode()])
      // The app's defaults, a one minute staleTime and no focus refetch.
      const { result } = renderCodes(createClient({ staleTime: 60_000, refetchOnWindowFocus: false }))
      await waitFor(() => expect(result.current.isSuccess).toBe(true))
      expect(served.fetches).toBe(1)

      // Turned off in another tab, then this tab comes back.
      served.codes = [makeCode({ isActive: false })]
      act(() => {
        window.dispatchEvent(new Event('visibilitychange'))
      })

      await waitFor(() => expect(result.current.data?.[0].isActive).toBe(false))
      expect(served.fetches).toBe(2)
    })
  })
})
