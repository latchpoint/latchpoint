import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { renderWithProviders } from '@/test/render'
import type { ComponentProps } from 'react'
import {
  type CachedDoorCode,
  DOOR_CODES_SETTLING_POLL_MS,
  useDeleteDoorCodeMutation,
  useDoorCodesQuery,
  useReadCachedDoorCode,
  useRetryDoorCodePushMutation,
} from '@/hooks/useDoorCodesQueries'
import { DoorCodeCard } from './DoorCodeCard'
import type { DoorCode } from '@/types'

const INACTIVE_MESSAGE = 'Door code is inactive. Turn it on before pushing it to its locks.'
// The page's selected user. Deliberately not the codes' userId, so the card
// can't be relying on code.userId to find the cache.
const PAGE_USER_ID = 'selected-user'

function makeCode(overrides: Partial<DoorCode> = {}): DoorCode {
  return {
    id: 7,
    userId: '00000000-0000-0000-0000-000000000001',
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
    lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: null, pendingRemoval: false }],
    pendingSlotClears: [],
    pushState: 'failed',
    lastPushError: 'Gateway timeout after 5.0s',
    lastPushAttemptAt: '2026-10-28T10:00:00Z',
    createdAt: '',
    updatedAt: '',
    ...overrides,
  }
}

const pushedCode = (lastPushAttemptAt: string) =>
  makeCode({
    pushState: 'pushed',
    lastPushError: '',
    lastPushAttemptAt,
    lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 3, pendingRemoval: false }],
  })

function conflict() {
  return HttpResponse.json({ error: { status: 'conflict', message: INACTIVE_MESSAGE } }, { status: 409 })
}

function timeout(message = 'Lock timed out') {
  return HttpResponse.json({ error: { status: 'timeout', message } }, { status: 504 })
}

// Lets the queued query and mutation notifications reach React.
const settle = () => new Promise((resolve) => setTimeout(resolve, 50))

function deferred() {
  let release: () => void = () => {}
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

type CardExtras = { codesUpdatedAt: number; readCachedCode: (id: number) => CachedDoorCode | null }

function card(
  code: DoorCode,
  retry: ReturnType<typeof useRetryDoorCodePushMutation>,
  extras: CardExtras,
  overrides: Partial<ComponentProps<typeof DoorCodeCard>> = {},
) {
  return (
    <DoorCodeCard
      key={code.id}
      code={code}
      canManage
      isEditing={false}
      lockNameByEntityId={new Map([['lock.front_door', 'Front Door']])}
      locks={[]}
      locksIsLoading={false}
      locksError={null}
      isSaving={false}
      isDeleting={false}
      isRetryingPush={retry.isPending && retry.variables === code.id}
      onBeginEdit={vi.fn()}
      onCloseEdit={vi.fn()}
      onUpdate={vi.fn()}
      onDelete={vi.fn()}
      onRetryPush={(id) => retry.mutateAsync(id)}
      codesUpdatedAt={extras.codesUpdatedAt}
      readCachedCode={extras.readCachedCode}
      {...overrides}
    />
  )
}

// The card wired to the real Retry mutation with the code passed in, so tests
// can rerender it with whatever state they need.
function CardWithRetry({
  code,
  codesUpdatedAt = 0,
  readCachedCode = () => null,
}: { code: DoorCode } & Partial<CardExtras>) {
  const retry = useRetryDoorCodePushMutation(PAGE_USER_ID)
  return card(code, retry, { codesUpdatedAt, readCachedCode })
}

// The card fed from the real door codes query, the way DoorCodesPage does it.
function CardsFromQuery() {
  const codesQuery = useDoorCodesQuery({ userId: PAGE_USER_ID, isAdmin: true })
  const retry = useRetryDoorCodePushMutation(PAGE_USER_ID)
  const readCachedCode = useReadCachedDoorCode(PAGE_USER_ID)
  return (
    <>
      <input aria-label="Other field" />
      {(codesQuery.data || []).map((code) =>
        card(code, retry, { codesUpdatedAt: codesQuery.dataUpdatedAt, readCachedCode }),
      )}
    </>
  )
}

// The card open for editing, with the real delete mutation.
function EditingCardFromQuery() {
  const codesQuery = useDoorCodesQuery({ userId: PAGE_USER_ID, isAdmin: true })
  const retry = useRetryDoorCodePushMutation(PAGE_USER_ID)
  const deleteMutation = useDeleteDoorCodeMutation(PAGE_USER_ID)
  const readCachedCode = useReadCachedDoorCode(PAGE_USER_ID)
  return (
    <>
      {(codesQuery.data || []).map((code) =>
        card(
          code,
          retry,
          { codesUpdatedAt: codesQuery.dataUpdatedAt, readCachedCode },
          {
            isEditing: true,
            isDeleting: deleteMutation.isPending,
            onDelete: (id, reauthPassword) => deleteMutation.mutateAsync({ id, reauthPassword }),
          },
        ),
      )}
    </>
  )
}

describe('DoorCodeCard', () => {
  it('marks a lock whose removal is still waiting on its slot clear', () => {
    const code = makeCode({
      lockEntityIds: ['lock.back_door', 'lock.front_door'],
      lockSlotAssignments: [
        { lockEntityId: 'lock.back_door', slotIndex: 2, pendingRemoval: false },
        { lockEntityId: 'lock.front_door', slotIndex: 1, pendingRemoval: true },
      ],
      pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 1, removing: true }],
    })

    renderWithProviders(<CardWithRetry code={code} />)

    expect(screen.getByText('Front Door (removing)')).toBeTruthy()
    expect(screen.getByText('lock.back_door')).toBeTruthy()
  })

  it('shows a refused delete turning the code off and keeps its error', async () => {
    const refusal =
      "Couldn't clear slot 3 on lock.front_door, it may still hold the PIN. The door code wasn't deleted and is now off, try again when the lock responds."
    let serverCode = pushedCode('2026-10-28T10:00:00Z')
    server.use(
      http.get('/api/door-codes/', () => HttpResponse.json({ data: [serverCode] })),
      http.delete('/api/door-codes/7/', () => {
        // What #144 leaves after refusing: off, pending, the slot still tracked.
        serverCode = makeCode({
          isActive: false,
          pushState: 'pending',
          lastPushError: "Couldn't clear slot 3 on lock.front_door, it may still hold the PIN",
          lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 3, pendingRemoval: false }],
          pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }],
        })
        return HttpResponse.json({ error: { status: 'gateway_error', message: refusal, gateway: 'zwavejs' } }, { status: 502 })
      }),
    )
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    try {
      renderWithProviders(<EditingCardFromQuery />)
      expect(await screen.findByText(/On lock:.*Front Door.*slot 3/)).toBeTruthy()
      expect(screen.queryByText('Inactive')).toBeNull()
      fireEvent.change(screen.getByLabelText(/Re-authenticate/), { target: { value: 'pw' } })
      fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

      expect(await screen.findByText('Inactive')).toBeTruthy()
      expect(await screen.findByText('Pending clear')).toBeTruthy()
      expect(await screen.findByText(refusal)).toBeTruthy()

      // The refetched code resets the form, but not the delete error.
      await settle()
      expect(screen.getByText(refusal)).toBeTruthy()
      expect(screen.getByText('Inactive')).toBeTruthy()
      // The Active toggle wasn't touched, so it follows the server.
      expect(screen.getByRole('switch', { name: 'Active' })).toHaveAttribute('aria-checked', 'false')
    } finally {
      confirmSpy.mockRestore()
    }
  })

  it('imports', async () => {
    const mod = await import('./DoorCodeCard')
    expect(mod).toBeTruthy()
  })

  it('shows the error when Retry is refused', async () => {
    server.use(http.post('/api/door-codes/7/push/', conflict))

    renderWithProviders(<CardWithRetry code={makeCode()} />)
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(INACTIVE_MESSAGE)
  })

  it('shows the status text when Retry fails without an error body', async () => {
    server.use(http.post('/api/door-codes/7/push/', () => new HttpResponse(null, { status: 502 })))

    renderWithProviders(<CardWithRetry code={makeCode()} />)
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Bad Gateway')
  })

  it('replaces the error with the new one when Retry fails again', async () => {
    let calls = 0
    server.use(
      http.post('/api/door-codes/7/push/', () => {
        calls += 1
        return timeout(calls === 1 ? 'Lock timed out' : 'Lock is still asleep')
      }),
    )

    renderWithProviders(<CardWithRetry code={makeCode()} />)
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

    fireEvent.click(await screen.findByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByText('Lock is still asleep')).toBeTruthy()
    expect(screen.queryByText('Lock timed out')).toBeNull()
  })

  it('has no error once a Retry after a failed one works', async () => {
    let calls = 0
    const second = deferred()
    server.use(
      http.post('/api/door-codes/7/push/', async () => {
        calls += 1
        if (calls === 1) return timeout()
        await second.promise
        return HttpResponse.json({ data: makeCode({ pushState: 'pending', lastPushError: '' }) })
      }),
    )

    renderWithProviders(<CardWithRetry code={makeCode()} />)
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByRole('button', { name: /Retrying/ })).toBeDisabled()
    second.release()

    // Only check once the second Retry has resolved and the button is back.
    expect(await screen.findByRole('button', { name: /^Retry$/ })).toBeEnabled()
    expect(calls).toBe(2)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('clears a refused Retry error once the code is turned back on and pushed', async () => {
    let serverCode = makeCode()
    server.use(
      http.get('/api/door-codes/', () => HttpResponse.json({ data: [serverCode] })),
      http.post('/api/door-codes/7/push/', () => {
        serverCode = makeCode({ isActive: false, pushState: 'pushed', lastPushError: '' })
        return conflict()
      }),
    )

    const { queryClient } = renderWithProviders(<CardsFromQuery />)
    fireEvent.click(await screen.findByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByText('Not on lock')).toBeTruthy()
    expect(await screen.findByRole('alert')).toHaveTextContent(INACTIVE_MESSAGE)

    // A refetch with nothing new keeps the error.
    await queryClient.invalidateQueries()
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent(INACTIVE_MESSAGE)

    // Someone turns it back on and it lands on the lock.
    serverCode = pushedCode('2026-10-28T10:05:00Z')
    await queryClient.invalidateQueries()

    expect(await screen.findByText(/On lock:.*Front Door.*slot 3/)).toBeTruthy()
    expect(screen.getByText('Active')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('clears a timed out Retry error once the scheduler pushes the code', async () => {
    let serverCode = makeCode()
    server.use(
      http.get('/api/door-codes/', () => HttpResponse.json({ data: [serverCode] })),
      http.post('/api/door-codes/7/push/', () => {
        // The attempt is recorded on the row before the timeout comes back.
        serverCode = makeCode({ lastPushAttemptAt: '2026-10-28T10:10:00Z', lastPushError: 'Lock timed out' })
        return timeout()
      }),
    )

    const { queryClient } = renderWithProviders(<CardsFromQuery />)
    fireEvent.click(await screen.findByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

    await queryClient.invalidateQueries()
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent('Lock timed out')

    serverCode = pushedCode('2026-10-28T10:15:00Z')
    await queryClient.invalidateQueries()

    expect(await screen.findByText(/On lock:.*Front Door.*slot 3/)).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('pins the error to the cached codes, even if a render skips straight past them', async () => {
    // The cache had the code failed at time 10 when the Retry was refused.
    const readCachedCode = () => ({ code: makeCode(), dataUpdatedAt: 10 })
    server.use(http.post('/api/door-codes/7/push/', () => timeout()))

    const { rerender } = renderWithProviders(
      <CardWithRetry code={makeCode()} codesUpdatedAt={5} readCachedCode={readCachedCode} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

    // Props older than the pinned data don't clear it, whatever they show.
    rerender(
      <CardWithRetry code={pushedCode('2026-10-28T09:00:00Z')} codesUpdatedAt={5} readCachedCode={readCachedCode} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Lock timed out')

    // Newer data with a different state clears it, without ever rendering time 10.
    rerender(
      <CardWithRetry code={pushedCode('2026-10-28T10:15:00Z')} codesUpdatedAt={20} readCachedCode={readCachedCode} />,
    )
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('keeps the refused Retry error through its own refetch and moves focus to it', async () => {
    // The page shows the code active but it was turned off elsewhere.
    let serverCode = makeCode()
    server.use(
      http.get('/api/door-codes/', () => HttpResponse.json({ data: [serverCode] })),
      http.post('/api/door-codes/7/push/', () => {
        serverCode = makeCode({ isActive: false, pushState: 'pushed', lastPushError: '' })
        return conflict()
      }),
    )

    renderWithProviders(<CardsFromQuery />)
    const retryButton = await screen.findByRole('button', { name: /^Retry$/ })
    retryButton.focus()
    fireEvent.click(retryButton)

    // The refetch removes the focused Retry button.
    expect(await screen.findByText('Not on lock')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(INACTIVE_MESSAGE)
    await waitFor(() => expect(alert).toHaveFocus())

    // Still there after everything has settled.
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent(INACTIVE_MESSAGE)
  })

  it('leaves focus alone when it moved elsewhere while the Retry ran', async () => {
    let serverCode = makeCode()
    const held = deferred()
    server.use(
      http.get('/api/door-codes/', () => HttpResponse.json({ data: [serverCode] })),
      http.post('/api/door-codes/7/push/', async () => {
        await held.promise
        serverCode = makeCode({ isActive: false, pushState: 'pushed', lastPushError: '' })
        return conflict()
      }),
    )

    renderWithProviders(<CardsFromQuery />)
    const retryButton = await screen.findByRole('button', { name: /^Retry$/ })
    retryButton.focus()
    fireEvent.click(retryButton)
    expect(await screen.findByRole('button', { name: /Retrying/ })).toBeTruthy()

    const otherField = screen.getByRole('textbox', { name: 'Other field' })
    otherField.focus()
    held.release()

    expect(await screen.findByText('Not on lock')).toBeTruthy()
    expect(await screen.findByRole('alert')).toHaveTextContent(INACTIVE_MESSAGE)
    await settle()
    expect(otherField).toHaveFocus()
  })

  it('does not offer Retry for an inactive code with nothing left to clear', () => {
    renderWithProviders(<CardWithRetry code={makeCode({ isActive: false, pushState: 'pushed' })} />)

    expect(screen.getByText('Inactive')).toBeTruthy()
    expect(screen.getByText('Not on lock')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })

  describe('while a code settles', () => {
    afterEach(() => {
      vi.useRealTimers()
    })

    const nextPoll = () => act(() => vi.advanceTimersByTimeAsync(DOOR_CODES_SETTLING_POLL_MS))

    it('moves from Pending clear to Not on lock once the scheduler clears the slot', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      let serverCode = makeCode({
        isActive: false,
        pushState: 'pushed',
        lastPushError: '',
        lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 3, pendingRemoval: false }],
        pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }],
      })
      server.use(http.get('/api/door-codes/', () => HttpResponse.json({ data: [serverCode] })))

      renderWithProviders(<CardsFromQuery />)
      expect(await screen.findByText('Pending clear')).toBeTruthy()

      serverCode = makeCode({ isActive: false, pushState: 'pushed', lastPushError: '' })
      await nextPoll()

      expect(await screen.findByText('Not on lock')).toBeTruthy()
      expect(screen.queryByText('Pending clear')).toBeNull()
    })

    it('keeps a Retry error through a poll with nothing new and drops it once the code is pushed', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      let serverCode = makeCode({ pushState: 'pending', lastPushError: '' })
      server.use(
        http.get('/api/door-codes/', () => HttpResponse.json({ data: [serverCode] })),
        http.post('/api/door-codes/7/push/', () => {
          serverCode = makeCode({ pushState: 'pending', lastPushError: '', lastPushAttemptAt: '2026-10-28T10:10:00Z' })
          return timeout()
        }),
      )

      renderWithProviders(<CardsFromQuery />)
      fireEvent.click(await screen.findByRole('button', { name: 'Retry now' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

      await nextPoll()
      await settle()
      expect(screen.getByText('Pending sync')).toBeTruthy()
      expect(screen.getByRole('alert')).toHaveTextContent('Lock timed out')

      serverCode = pushedCode('2026-10-28T10:15:00Z')
      await nextPoll()

      expect(await screen.findByText(/On lock:.*Front Door.*slot 3/)).toBeTruthy()
      expect(screen.queryByRole('alert')).toBeNull()
    })
  })
})
