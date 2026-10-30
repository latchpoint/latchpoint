import { createElement, type PropsWithChildren } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { queryKeys } from '@/types'
import type { DoorCode } from '@/types'
import {
  DOOR_CODES_FAST_POLL_MS,
  DOOR_CODES_FAST_POLL_WINDOW_MS,
  DOOR_CODES_SETTLING_POLL_MS,
  doorCodesRefetchInterval,
  hasQueuedPush,
  isDoorCodeSettling,
  isLockQueued,
  useCreateDoorCodeMutation,
  useDeleteDoorCodeMutation,
  useDoorCodesQuery,
  useReadCachedDoorCode,
  useRetryDoorCodePushMutation,
  useUpdateDoorCodeMutation,
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

    describe('with per-lock push state', () => {
      type Slot = DoorCode['lockSlotAssignments'][number]
      const lockOf = (lockEntityId: string, overrides: Partial<Slot> = {}): Slot => ({
        lockEntityId,
        slotIndex: null,
        pendingRemoval: false,
        pushState: 'pending',
        lastPushError: '',
        lastPushAttemptAt: null,
        pushAttemptCount: 0,
        schedulePending: false,
        ...overrides,
      })
      // Failed on the back door, whatever the front door is doing.
      const failedWith = (frontDoor: Partial<Slot>, overrides: Partial<DoorCode> = {}) =>
        makeCode({
          pushState: 'failed',
          lastPushError: 'lock.back_door: Lock rejected the PIN',
          lockEntityIds: ['lock.back_door', 'lock.front_door'],
          lockSlotAssignments: [
            lockOf('lock.back_door', { pushState: 'failed', lastPushError: 'Lock rejected the PIN' }),
            lockOf('lock.front_door', frontDoor),
          ],
          ...overrides,
        })

      it('is settling while a lock is pending under a failed code, since the scheduler still retries it', () => {
        expect(isDoorCodeSettling(failedWith({ pushState: 'pending' }))).toBe(true)
      })

      it("is settling while a lock's schedule is pending under a failed code", () => {
        expect(isDoorCodeSettling(failedWith({ pushState: 'pending', slotIndex: 4, schedulePending: true }))).toBe(true)
      })

      it('is settled once every other lock is pushed or failed too', () => {
        expect(isDoorCodeSettling(failedWith({ pushState: 'pushed', slotIndex: 2 }))).toBe(false)
        // A schedule that failed for good waits for a Retry like any failed lock.
        expect(
          isDoorCodeSettling(failedWith({ pushState: 'failed', slotIndex: 2, schedulePending: true })),
        ).toBe(false)
      })

      it("doesn't count a pending lock that's being dropped, or one of a code that's off or not started", () => {
        expect(isDoorCodeSettling(failedWith({ pushState: 'pending', pendingRemoval: true }))).toBe(false)
        expect(isDoorCodeSettling(failedWith({ pushState: 'pending' }, { isActive: false }))).toBe(false)
        expect(
          isDoorCodeSettling(failedWith({ pushState: 'pending' }, { validity: 'scheduled', pendingSlotClears: [] })),
        ).toBe(false)
      })

      it("is settling while a pending code's lock waits on its schedule, even though it holds a slot", () => {
        const code = makeCode({
          pushState: 'pending',
          lockSlotAssignments: [lockOf('lock.front_door', { slotIndex: 4, schedulePending: true })],
        })
        expect(isDoorCodeSettling(code)).toBe(true)
      })

      it("is settled when the only lock left waits on a slot whose clear hit the cap, since nothing's sent to it", () => {
        // A PIN change whose clear of slot 3 failed until the clear-retry cap failed the code.
        const code = makeCode({
          pushState: 'failed',
          lockSlotAssignments: [lockOf('lock.front_door', { slotIndex: 3, pushState: 'pending', schedulePending: true })],
          pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }],
        })
        expect(isDoorCodeSettling(code)).toBe(false)
      })

      it('is settled when a failed code has another lock waiting on a slot whose clear is outstanding', () => {
        const code = failedWith(
          { pushState: 'pending', slotIndex: 3, schedulePending: true },
          { pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }] },
        )
        expect(isDoorCodeSettling(code)).toBe(false)
      })

      it('still counts a lock waiting on its schedule when the clear is for that slot number on another lock', () => {
        const code = failedWith(
          { pushState: 'pending', slotIndex: 3, schedulePending: true },
          { pendingSlotClears: [{ lockEntityId: 'lock.back_door', slotIndex: 3, removing: false }] },
        )
        expect(isDoorCodeSettling(code)).toBe(true)
      })

      it('still counts a lock waiting on its schedule when the clear is for another slot on that lock', () => {
        const code = failedWith(
          { pushState: 'pending', slotIndex: 3, schedulePending: true },
          { pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 5, removing: false }] },
        )
        expect(isDoorCodeSettling(code)).toBe(true)
      })

      it('is settling while a save or Retry has a lock queued, even under a failed code (#124)', () => {
        const queued = { pushState: 'pending' as const, pushRequestedAt: '2026-10-30T10:05:00Z' }
        expect(isDoorCodeSettling(makeCode({ pushState: 'pending', lockSlotAssignments: [lockOf('lock.front_door', queued)] }))).toBe(true)
        expect(isDoorCodeSettling(failedWith(queued))).toBe(true)
        expect(isDoorCodeSettling(failedWith({ ...queued, slotIndex: 4, schedulePending: true }))).toBe(true)
      })

      it('falls back to the code-level state when the API sends no per-lock fields', () => {
        const withoutPerLock = (pushState: DoorCode['pushState']) =>
          makeCode({
            pushState,
            lockEntityIds: ['lock.back_door', 'lock.front_door'],
            lockSlotAssignments: [
              { lockEntityId: 'lock.back_door', slotIndex: null, pendingRemoval: false },
              { lockEntityId: 'lock.front_door', slotIndex: null, pendingRemoval: false },
            ],
          })
        expect(isDoorCodeSettling(withoutPerLock('failed'))).toBe(false)
        expect(isDoorCodeSettling(withoutPerLock('pending'))).toBe(true)
      })
    })
  })

  describe('isLockQueued', () => {
    type Slot = DoorCode['lockSlotAssignments'][number]
    const requestedAt = '2026-10-30T10:05:00Z'
    const slot = (overrides: Partial<Slot> = {}): Slot => ({
      lockEntityId: 'lock.front_door',
      slotIndex: null,
      pendingRemoval: false,
      pushState: 'pending',
      lastPushError: '',
      lastPushAttemptAt: null,
      pushAttemptCount: 0,
      schedulePending: false,
      pushRequestedAt: requestedAt,
      ...overrides,
    })
    const queued = (assignment: Slot, overrides: Partial<DoorCode> = {}) =>
      isLockQueued(makeCode({ pushState: 'pending', lockSlotAssignments: [assignment], ...overrides }), assignment)

    it('is queued until a push attempt comes after the request', () => {
      expect(queued(slot())).toBe(true)
      expect(queued(slot({ lastPushAttemptAt: '2026-10-30T10:00:00Z' }))).toBe(true)
      expect(queued(slot({ lastPushAttemptAt: requestedAt }))).toBe(false)
      expect(queued(slot({ lastPushAttemptAt: '2026-10-30T10:05:01Z' }))).toBe(false)
    })

    it('compares the times, not the strings', () => {
      // The same instant as the request, written with an offset.
      expect(queued(slot({ lastPushAttemptAt: '2026-10-30T06:05:00-04:00' }))).toBe(false)
    })

    it("isn't queued for an API without pushRequestedAt", () => {
      expect(queued(slot({ pushRequestedAt: undefined }))).toBe(false)
      expect(queued(slot({ pushRequestedAt: null }))).toBe(false)
    })

    it("isn't queued once the lock is pushed or failed, or doesn't need a push", () => {
      expect(queued(slot({ pushState: 'pushed', slotIndex: 2 }))).toBe(false)
      expect(queued(slot({ pushState: 'failed' }))).toBe(false)
      expect(queued(slot({ slotIndex: 2 }))).toBe(false)
      expect(queued(slot({ slotIndex: 2, schedulePending: true }))).toBe(true)
      expect(queued(slot({ pendingRemoval: true }))).toBe(false)
      expect(
        queued(slot({ slotIndex: 2, schedulePending: true }), {
          pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 2, removing: false }],
        }),
      ).toBe(false)
    })

    it("isn't queued on a code that's off, not started or expired", () => {
      expect(queued(slot(), { isActive: false })).toBe(false)
      expect(queued(slot(), { validity: 'scheduled' })).toBe(false)
      expect(queued(slot(), { validity: 'expired' })).toBe(false)
    })

    describe("with the server's pushQueued (#205)", () => {
      it('is queued after the schedule re-queue, 1µs after the attempt', () => {
        // Both stamps read as the same millisecond in the browser.
        const sameMs = '2026-10-30T10:05:00.123Z'
        const requeued = slot({ slotIndex: 2, schedulePending: true, lastPushAttemptAt: sameMs, pushRequestedAt: sameMs })
        expect(queued(requeued)).toBe(false)
        expect(queued({ ...requeued, pushQueued: true })).toBe(true)
      })

      it("isn't queued once the request lapsed or the lock hit the cap, which only the server knows", () => {
        expect(queued(slot())).toBe(true)
        expect(queued(slot({ pushQueued: false }))).toBe(false)
        expect(queued(slot({ pushAttemptCount: 24, pushQueued: false }))).toBe(false)
      })

      it('falls back to the timestamps without it', () => {
        expect(queued(slot({ pushQueued: undefined }))).toBe(true)
        expect(queued(slot({ pushQueued: undefined, lastPushAttemptAt: '2026-10-30T10:05:01Z' }))).toBe(false)
      })
    })
  })

  describe('hasQueuedPush', () => {
    const lock = (overrides: Partial<DoorCode['lockSlotAssignments'][number]> = {}) => ({
      lockEntityId: 'lock.front_door',
      slotIndex: null,
      pendingRemoval: false,
      pushState: 'pending' as const,
      pushRequestedAt: '2026-10-30T10:05:00Z',
      ...overrides,
    })

    it('is true when any lock in the response is queued', () => {
      expect(hasQueuedPush(pendingPush({ lockSlotAssignments: [lock({ pushQueued: true })] }))).toBe(true)
      expect(
        hasQueuedPush(
          pendingPush({
            lockSlotAssignments: [lock({ lockEntityId: 'lock.back_door', pushQueued: false }), lock({ pushQueued: true })],
          }),
        ),
      ).toBe(true)
      // An API from before #205, from the timestamps.
      expect(hasQueuedPush(pendingPush({ lockSlotAssignments: [lock()] }))).toBe(true)
    })

    it('is false when nothing was queued, or there is no code', () => {
      expect(hasQueuedPush(pendingPush({ lockSlotAssignments: [lock({ pushQueued: false })] }))).toBe(false)
      expect(hasQueuedPush(pendingPush())).toBe(false)
      expect(hasQueuedPush(makeCode())).toBe(false)
      expect(hasQueuedPush(undefined)).toBe(false)
    })
  })

  describe('doorCodesRefetchInterval', () => {
    const now = 1_000_000

    it('polls fast for a minute after a save or Retry while a code is settling', () => {
      expect(doorCodesRefetchInterval([pendingPush()], now, now)).toBe(DOOR_CODES_FAST_POLL_MS)
      expect(doorCodesRefetchInterval([pendingPush()], now - DOOR_CODES_FAST_POLL_WINDOW_MS + 1, now)).toBe(
        DOOR_CODES_FAST_POLL_MS,
      )
    })

    it('drops back to the settling poll after the minute, or with no save at all', () => {
      expect(doorCodesRefetchInterval([pendingPush()], now - DOOR_CODES_FAST_POLL_WINDOW_MS, now)).toBe(
        DOOR_CODES_SETTLING_POLL_MS,
      )
      expect(doorCodesRefetchInterval([pendingPush()], undefined, now)).toBe(DOOR_CODES_SETTLING_POLL_MS)
    })

    it("doesn't poll when nothing is settling, even right after a save", () => {
      expect(doorCodesRefetchInterval([makeCode()], now, now)).toBe(false)
      expect(doorCodesRefetchInterval(undefined, now, now)).toBe(false)
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

    it('keeps polling a failed code while another of its locks is still being retried', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const slot = (lockEntityId: string, pushState: DoorCode['pushState'], slotIndex: number | null = null) => ({
        lockEntityId,
        slotIndex,
        pendingRemoval: false,
        pushState,
      })
      const failedOn = (frontState: DoorCode['pushState']) =>
        makeCode({
          pushState: 'failed',
          lastPushError: 'lock.back_door: Lock rejected the PIN',
          lockEntityIds: ['lock.back_door', 'lock.front_door'],
          lockSlotAssignments: [
            slot('lock.back_door', 'failed'),
            slot('lock.front_door', frontState, frontState === 'pushed' ? 2 : null),
          ],
        })
      const served = serveCodes([failedOn('pending')])
      const { result } = renderCodes()
      await waitFor(() => expect(result.current.data?.[0].lockSlotAssignments[1].pushState).toBe('pending'))
      expect(served.fetches).toBe(1)

      await act(() => vi.advanceTimersByTimeAsync(DOOR_CODES_SETTLING_POLL_MS))
      await waitFor(() => expect(served.fetches).toBe(2))

      // The front door lands, only a Retry moves the back door now.
      served.codes = [failedOn('pushed')]
      await act(() => vi.advanceTimersByTimeAsync(DOOR_CODES_SETTLING_POLL_MS))
      await waitFor(() => expect(result.current.data?.[0].lockSlotAssignments[1].pushState).toBe('pushed'))
      expect(served.fetches).toBe(3)

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

    describe('after a save or Retry (#124)', () => {
      const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))
      // Lets a fetch that just landed reach the observer, which resets its interval.
      const flush = () => act(() => vi.advanceTimersByTimeAsync(50))

      // The codes query and the three mutations that queue a push, on one client.
      const renderPage = (client = createClient()) =>
        renderHook(
          () => ({
            codes: useDoorCodesQuery({ userId: 'user-1', isAdmin: true }),
            create: useCreateDoorCodeMutation('user-1'),
            update: useUpdateDoorCodeMutation('user-1'),
            retry: useRetryDoorCodePushMutation('user-1'),
          }),
          { wrapper: wrap(client) },
        )
      type Page = ReturnType<typeof renderPage>['result']['current']

      // A code whose lock is queued for the scheduler, as a save that queued its push returns it.
      const queuedPush = () =>
        pendingPush({
          lockSlotAssignments: [
            {
              lockEntityId: 'lock.front_door',
              slotIndex: null,
              pendingRemoval: false,
              pushState: 'pending',
              pushRequestedAt: '2026-10-30T10:05:00Z',
              pushQueued: true,
            },
          ],
        })

      // Each one answers right away and leaves the code waiting on the scheduler.
      function serveSaves(served: { codes: DoorCode[] }) {
        const queued = () => {
          served.codes = [queuedPush()]
          return HttpResponse.json({ data: served.codes[0] })
        }
        server.use(
          http.post('/api/door-codes/', queued),
          http.patch('/api/door-codes/7/', queued),
          http.post('/api/door-codes/7/push/', queued),
        )
      }

      it.each<[string, (page: Page) => Promise<unknown>]>([
        ['a create', (page) => page.create.mutateAsync({ code: '1234', lockEntityIds: ['lock.front_door'], reauthPassword: 'pw' })],
        ['an update', (page) => page.update.mutateAsync({ id: 7, req: { code: '5678', reauthPassword: 'pw' } })],
        ['a Retry', (page) => page.retry.mutateAsync(7)],
      ])('polls every 2s for a minute after %s, then every 15s', async (_what, save) => {
        vi.useFakeTimers({ shouldAdvanceTime: true })
        const served = serveCodes([makeCode()])
        serveSaves(served)
        const { result } = renderPage()
        await waitFor(() => expect(result.current.codes.isSuccess).toBe(true))

        await act(() => save(result.current))
        await waitFor(() => expect(served.fetches).toBe(2))
        await flush()

        await advance(DOOR_CODES_FAST_POLL_MS)
        await waitFor(() => expect(served.fetches).toBe(3))
        await flush()
        await advance(DOOR_CODES_FAST_POLL_MS)
        await waitFor(() => expect(served.fetches).toBe(4))
        await flush()

        // The minute is up. The fast poll already set up still runs once, and
        // the interval worked out after it is the 15s one.
        vi.setSystemTime(Date.now() + DOOR_CODES_FAST_POLL_WINDOW_MS)
        await advance(DOOR_CODES_FAST_POLL_MS)
        await waitFor(() => expect(served.fetches).toBe(5))
        await flush()

        await advance(DOOR_CODES_FAST_POLL_MS * 3)
        expect(served.fetches).toBe(5)
        await advance(DOOR_CODES_SETTLING_POLL_MS - DOOR_CODES_FAST_POLL_MS * 2)
        await waitFor(() => expect(served.fetches).toBe(6))
      })

      it("doesn't poll after a save that leaves nothing settling", async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true })
        const served = serveCodes([makeCode()])
        server.use(http.patch('/api/door-codes/7/', () => HttpResponse.json({ data: makeCode({ label: 'Back' }) })))
        const { result } = renderPage()
        await waitFor(() => expect(result.current.codes.isSuccess).toBe(true))

        await act(() => result.current.update.mutateAsync({ id: 7, req: { label: 'Back', reauthPassword: 'pw' } }))
        await waitFor(() => expect(served.fetches).toBe(2))

        await advance(DOOR_CODES_SETTLING_POLL_MS * 2)
        expect(served.fetches).toBe(2)
      })

      // The codes poll every 15s, not every 2s, after `save` (#205).
      async function expectSettlingPollOnly(served: { fetches: number }) {
        await waitFor(() => expect(served.fetches).toBe(2))
        await flush()
        await advance(DOOR_CODES_FAST_POLL_MS * 3)
        expect(served.fetches).toBe(2)
        await advance(DOOR_CODES_SETTLING_POLL_MS - DOOR_CODES_FAST_POLL_MS * 3)
        await waitFor(() => expect(served.fetches).toBe(3))
      }

      it("doesn't poll fast after an update that only clears, eg turning a code off (#205)", async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true })
        const served = serveCodes([makeCode()])
        // Off, with its slot still to clear: settling, but nothing queued.
        const clearing = makeCode({
          isActive: false,
          pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }],
          lockSlotAssignments: [
            {
              lockEntityId: 'lock.front_door',
              slotIndex: 3,
              pendingRemoval: false,
              pushState: 'pending',
              pushRequestedAt: '2026-10-30T10:05:00Z',
              pushQueued: false,
            },
          ],
        })
        server.use(
          http.patch('/api/door-codes/7/', () => {
            served.codes = [clearing]
            return HttpResponse.json({ data: clearing })
          }),
        )
        const { result } = renderPage()
        await waitFor(() => expect(result.current.codes.isSuccess).toBe(true))

        await act(() => result.current.update.mutateAsync({ id: 7, req: { isActive: false, reauthPassword: 'pw' } }))

        await expectSettlingPollOnly(served)
      })

      it.each<[string, DoorCode]>([
        // A process without the queued push task pushes in the request (#124).
        ['a save the backend pushed inline', pendingPush({ lastPushError: 'Lock timed out' })],
        [
          'a save whose request already lapsed or hit the cap',
          pendingPush({
            lockSlotAssignments: [
              {
                lockEntityId: 'lock.front_door',
                slotIndex: null,
                pendingRemoval: false,
                pushState: 'pending',
                pushRequestedAt: '2026-10-30T10:05:00Z',
                pushQueued: false,
              },
            ],
          }),
        ],
      ])("doesn't poll fast after %s", async (_what, saved) => {
        vi.useFakeTimers({ shouldAdvanceTime: true })
        const served = serveCodes([makeCode()])
        server.use(
          http.post('/api/door-codes/', () => {
            served.codes = [saved]
            return HttpResponse.json({ data: saved })
          }),
        )
        const { result } = renderPage()
        await waitFor(() => expect(result.current.codes.isSuccess).toBe(true))

        await act(() =>
          result.current.create.mutateAsync({ code: '1234', lockEntityIds: ['lock.front_door'], reauthPassword: 'pw' }),
        )

        await expectSettlingPollOnly(served)
      })

      it("doesn't poll fast after a refused Retry, since that's still answered in the request", async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true })
        const served = serveCodes([pendingPush()])
        server.use(
          http.post('/api/door-codes/7/push/', () =>
            HttpResponse.json({ error: { status: 'conflict', message: 'Door code is inactive.' } }, { status: 409 }),
          ),
        )
        const { result } = renderPage()
        await waitFor(() => expect(result.current.codes.isSuccess).toBe(true))

        await act(() => expect(result.current.retry.mutateAsync(7)).rejects.toMatchObject({ code: '409' }))
        await waitFor(() => expect(served.fetches).toBe(2))
        await flush()

        await advance(DOOR_CODES_FAST_POLL_MS * 3)
        expect(served.fetches).toBe(2)
        await advance(DOOR_CODES_SETTLING_POLL_MS)
        await waitFor(() => expect(served.fetches).toBe(3))
      })
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
