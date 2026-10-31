import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { renderWithProviders } from '@/test/render'
import type { ComponentProps } from 'react'
import {
  type CachedDoorCode,
  DOOR_CODES_FAST_POLL_MS,
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
    validity: 'valid',
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
  lockNameByEntityId,
}: { code: DoorCode; lockNameByEntityId?: Map<string, string> } & Partial<CardExtras>) {
  const retry = useRetryDoorCodePushMutation(PAGE_USER_ID)
  return card(code, retry, { codesUpdatedAt, readCachedCode }, lockNameByEntityId ? { lockNameByEntityId } : {})
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

  it('still shows a lock being removed when the API leaves it out of lockEntityIds', () => {
    // #171: lockEntityIds doesn't list it, lockSlotAssignments does.
    const code = makeCode({
      lockEntityIds: ['lock.back_door'],
      lockSlotAssignments: [
        { lockEntityId: 'lock.back_door', slotIndex: 2, pendingRemoval: false },
        { lockEntityId: 'lock.front_door', slotIndex: 1, pendingRemoval: true },
      ],
      pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 1, removing: true }],
    })

    renderWithProviders(<CardWithRetry code={code} />)

    expect(screen.getByText('Front Door (removing)')).toBeTruthy()
    expect(screen.getByText('lock.back_door')).toBeTruthy()
    expect(screen.queryByText('No locks')).toBeNull()
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

  describe('per-lock chips', () => {
    const lockNames = new Map([
      ['lock.back_door', 'Back Door'],
      ['lock.front_door', 'Front Door'],
    ])
    type Slot = DoorCode['lockSlotAssignments'][number]
    const back = (overrides: Partial<Slot> = {}): Slot => ({
      lockEntityId: 'lock.back_door',
      slotIndex: null,
      pendingRemoval: false,
      pushState: 'pushed',
      lastPushError: '',
      lastPushAttemptAt: null,
      pushAttemptCount: 0,
      schedulePending: false,
      ...overrides,
    })
    const front = (overrides: Partial<Slot> = {}): Slot => back({ lockEntityId: 'lock.front_door', ...overrides })
    const twoLocks = (lockSlotAssignments: Slot[], overrides: Partial<DoorCode> = {}) =>
      makeCode({
        lockEntityIds: ['lock.back_door', 'lock.front_door'],
        lockAssignments: [
          { id: 1, lockEntityId: 'lock.back_door' },
          { id: 2, lockEntityId: 'lock.front_door' },
        ],
        lockSlotAssignments,
        ...overrides,
      })
    const renderCard = (code: DoorCode) =>
      renderWithProviders(<CardWithRetry code={code} lockNameByEntityId={lockNames} />)

    it("shows a failed lock with its own error and the other lock's pending state", () => {
      renderCard(
        twoLocks(
          [
            back({ pushState: 'failed', lastPushError: 'Lock rejected the PIN', pushAttemptCount: 1 }),
            front({ pushState: 'pending', lastPushError: 'Lock timed out', pushAttemptCount: 3 }),
          ],
          { pushState: 'failed', lastPushError: 'lock.back_door: Lock rejected the PIN' },
        ),
      )

      expect(screen.getByText('Back Door (push failed)')).toHaveAttribute('title', 'Lock rejected the PIN')
      expect(screen.getByText('Front Door (pending)')).toHaveAttribute('title', 'Lock timed out')
      expect(screen.getByText('Push failed on Back Door, still retrying Front Door')).toBeTruthy()
      expect(screen.getByRole('button', { name: /^Retry$/ })).toBeTruthy()
    })

    it('says the push gave up when the cap failed a lock with no error of its own', () => {
      renderCard(
        twoLocks([back({ pushState: 'failed', pushAttemptCount: 24 }), front({ pushState: 'failed' })], {
          pushState: 'failed',
          lastPushError: 'lock.back_door: Push gave up after 24 attempts',
        }),
      )

      expect(screen.getByText('Back Door (push failed)')).toHaveAttribute(
        'title',
        'Push gave up after 24 attempts, Retry sends it again.',
      )
      expect(screen.getByText('Front Door (push failed)')).toHaveAttribute('title', 'Push failed, Retry sends it again.')
    })

    it('says attempt for a lock that gave up after one, and the schedule for one whose schedule failed', () => {
      renderCard(
        twoLocks(
          [
            back({ pushState: 'failed', pushAttemptCount: 1 }),
            front({ slotIndex: 4, pushState: 'failed', schedulePending: true, pushAttemptCount: 24 }),
          ],
          { pushState: 'failed' },
        ),
      )

      expect(screen.getByText('Back Door (push failed)')).toHaveAttribute(
        'title',
        'Push gave up after 1 attempt, Retry sends it again.',
      )
      expect(screen.getByText('Front Door (schedule not applied)')).toHaveAttribute(
        'title',
        "Its schedule couldn't be sent, Retry sends it again.",
      )
    })

    it('shows a lock waiting on its set as pending', () => {
      renderCard(twoLocks([back({ slotIndex: 2 }), front({ pushState: 'pending' })], { pushState: 'pending' }))

      expect(screen.getByText('Front Door (pending)')).toHaveAttribute(
        'title',
        'Waiting for the lock to accept the code.',
      )
      expect(screen.getByText('Back Door')).not.toHaveAttribute('title')
    })

    it('shows a lock with the PIN whose schedule is still being retried as schedule pending', () => {
      renderCard(
        twoLocks(
          [
            back({ slotIndex: 2 }),
            front({ slotIndex: 4, pushState: 'pending', schedulePending: true, pushAttemptCount: 1 }),
          ],
          { pushState: 'pending', daysOfWeek: 31, codeType: 'temporary' },
        ),
      )

      expect(screen.getByText('Front Door (schedule pending)')).toHaveAttribute(
        'title',
        'The PIN is on the lock, its schedule is still being sent.',
      )
      expect(screen.queryByText(/schedule not applied/)).toBeNull()
    })

    it("shows a schedule retry's last error on the schedule pending chip", () => {
      renderCard(
        twoLocks(
          [
            back({ slotIndex: 2 }),
            front({ slotIndex: 4, pushState: 'pending', schedulePending: true, lastPushError: 'Lock timed out' }),
          ],
          { pushState: 'pending' },
        ),
      )

      expect(screen.getByText('Front Door (schedule pending)')).toHaveAttribute('title', 'Lock timed out')
    })

    it('shows a schedule that failed for good as schedule not applied, with its error', () => {
      renderCard(
        twoLocks(
          [
            back({ slotIndex: 2 }),
            front({ slotIndex: 4, pushState: 'failed', schedulePending: true, lastPushError: 'Schedule rejected' }),
          ],
          { pushState: 'failed', lastPushError: 'lock.front_door: Schedule rejected' },
        ),
      )

      expect(screen.getByText('Front Door (schedule not applied)')).toHaveAttribute('title', 'Schedule rejected')
    })

    it('keeps removing for a lock being dropped, whatever its own state', () => {
      renderCard(
        twoLocks([back({ slotIndex: 2 }), front({ slotIndex: 1, pendingRemoval: true, pushState: 'pending' })], {
          pushState: 'pushed',
          pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 1, removing: true }],
        }),
      )

      expect(screen.getByText('Front Door (removing)')).toBeTruthy()
    })

    it("doesn't show a pushed lock as settled while one of its slots is left to clear", () => {
      renderCard(
        twoLocks([back({ slotIndex: 2 }), front({ slotIndex: 5 })], {
          pushState: 'pending',
          lastPushError: "Couldn't clear slot 3 on lock.front_door, it may still hold the PIN",
          pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }],
        }),
      )

      expect(screen.getByText('Front Door (clearing)')).toHaveAttribute(
        'title',
        'Slot 3 may still hold the PIN, retried automatically.',
      )
      expect(screen.getByText('Back Door')).toBeTruthy()
    })

    it('shows the clear as failed once the clear-retry cap failed the code', () => {
      renderCard(
        twoLocks([back({ slotIndex: 2 }), front({ slotIndex: 5 })], {
          pushState: 'failed',
          lastPushError: "Couldn't clear slot 3 on lock.front_door, it may still hold the PIN",
          pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }],
        }),
      )

      const chip = screen.getByText('Front Door (clear failed)')
      expect(chip).toHaveAttribute('title', 'Slot 3 may still hold the PIN, Retry tries the clear again.')
    })

    it('keeps clearing on one lock when the code is failed by another lock', () => {
      renderCard(
        twoLocks([back({ pushState: 'failed', lastPushError: 'Lock rejected the PIN' }), front({ slotIndex: 5 })], {
          pushState: 'failed',
          lastPushError: 'lock.back_door: Lock rejected the PIN',
          pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }],
        }),
      )

      expect(screen.getByText('Back Door (push failed)')).toBeTruthy()
      expect(screen.getByText('Front Door (clearing)')).toHaveAttribute(
        'title',
        'Slot 3 may still hold the PIN, retried automatically.',
      )
    })

    it('shows clearing before pending on a lock that has both', () => {
      // A PIN change whose clear of the old slot failed, with the new PIN still to go on.
      renderCard(
        twoLocks([back({ slotIndex: 2 }), front({ pushState: 'pending' })], {
          pushState: 'pending',
          pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }],
        }),
      )

      expect(screen.getByText('Front Door (clearing)')).toBeTruthy()
      expect(screen.queryByText('Front Door (pending)')).toBeNull()
    })

    it("says clearing, not clear failed, when an API without per-lock state can't say why the code failed", () => {
      renderCard(
        twoLocks(
          [
            { lockEntityId: 'lock.back_door', slotIndex: null, pendingRemoval: false },
            { lockEntityId: 'lock.front_door', slotIndex: 5, pendingRemoval: false },
          ],
          {
            pushState: 'failed',
            lastPushError: 'Lock rejected the PIN',
            pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }],
          },
        ),
      )

      expect(screen.getByText('Front Door (clearing)')).toBeTruthy()
      expect(screen.queryByText(/clear failed/)).toBeNull()
    })

    it("doesn't show a lock's push state on a code that's off its locks", () => {
      renderCard(
        twoLocks([back({ pushState: 'pending' }), front({ pushState: 'failed', lastPushError: 'old' })], {
          isActive: false,
          pushState: 'pushed',
          lastPushError: '',
        }),
      )

      expect(screen.getByText('Back Door')).toBeTruthy()
      expect(screen.getByText('Front Door')).toBeTruthy()
    })

    it('shows plain chips for an API without per-lock state', () => {
      renderCard(
        twoLocks(
          [
            { lockEntityId: 'lock.back_door', slotIndex: null, pendingRemoval: false },
            { lockEntityId: 'lock.front_door', slotIndex: null, pendingRemoval: false },
          ],
          { pushState: 'failed' },
        ),
      )

      expect(screen.getByText('Back Door')).toBeTruthy()
      expect(screen.getByText('Front Door')).toBeTruthy()
      expect(screen.getByText('Push failed: Gateway timeout after 5.0s')).toBeTruthy()
    })

    describe('a push a save or Retry queued (#124)', () => {
      const requestedAt = '2026-10-30T10:05:00Z'

      it('shows a lock not tried since the save as queued', () => {
        renderCard(
          twoLocks(
            [
              back({ pushState: 'pending', pushRequestedAt: requestedAt }),
              front({ pushState: 'pending', lastPushError: 'Lock timed out', lastPushAttemptAt: '2026-10-30T10:00:00Z', pushRequestedAt: requestedAt }),
            ],
            { pushState: 'pending' },
          ),
        )

        expect(screen.getByText('Back Door (queued)')).toHaveAttribute('title', 'Waiting to be sent to the lock.')
        // Its error is from the push before the save.
        expect(screen.getByText('Front Door (queued)')).toHaveAttribute('title', 'Waiting to be sent to the lock.')
      })

      it('shows queued ahead of schedule pending', () => {
        renderCard(
          twoLocks(
            [back({ slotIndex: 2 }), front({ pushState: 'pending', slotIndex: 4, schedulePending: true, pushRequestedAt: requestedAt })],
            { pushState: 'pending' },
          ),
        )

        expect(screen.getByText('Front Door (queued)')).toBeTruthy()
      })

      it('gives way to pending once the scheduler tried it, and push failed once it failed', () => {
        const tried = '2026-10-30T10:05:02Z'
        const { unmount } = renderCard(
          twoLocks(
            [
              back({ pushState: 'failed', lastPushError: 'Lock rejected the PIN', lastPushAttemptAt: tried, pushRequestedAt: requestedAt }),
              front({ pushState: 'pending', lastPushError: 'Lock timed out', lastPushAttemptAt: tried, pushRequestedAt: requestedAt }),
            ],
            { pushState: 'failed', lastPushError: 'lock.back_door: Lock rejected the PIN' },
          ),
        )

        expect(screen.getByText('Back Door (push failed)')).toHaveAttribute('title', 'Lock rejected the PIN')
        expect(screen.getByText('Front Door (pending)')).toHaveAttribute('title', 'Lock timed out')
        unmount()

        // An attempt at the same instant as the request used it up too.
        renderCard(twoLocks([back({ slotIndex: 2 }), front({ pushState: 'pending', lastPushAttemptAt: requestedAt, pushRequestedAt: requestedAt })]))
        expect(screen.getByText('Front Door (pending)')).toBeTruthy()
      })

      it('shows pending, not queued, for an API without pushRequestedAt', () => {
        renderCard(twoLocks([back({ slotIndex: 2 }), front({ pushState: 'pending' })], { pushState: 'pending' }))

        expect(screen.getByText('Front Door (pending)')).toBeTruthy()
        expect(screen.queryByText(/\(queued\)/)).toBeNull()
      })

      it("keeps clearing and removing ahead of queued, and doesn't show it on a code that's off its locks", () => {
        const { unmount } = renderCard(
          twoLocks(
            [
              back({ pushState: 'pending', pendingRemoval: true, slotIndex: 2, pushRequestedAt: requestedAt }),
              front({ pushState: 'pending', slotIndex: 3, schedulePending: true, pushRequestedAt: requestedAt }),
            ],
            { pushState: 'pending', pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }] },
          ),
        )
        expect(screen.getByText('Back Door (removing)')).toBeTruthy()
        expect(screen.getByText('Front Door (clearing)')).toBeTruthy()
        unmount()

        renderCard(twoLocks([back({ slotIndex: 2 }), front({ pushState: 'pending', pushRequestedAt: requestedAt })], { isActive: false }))
        expect(screen.queryByText(/\(queued\)/)).toBeNull()
      })

      // The test above passes whatever the chip order, since neither lock is
      // queued there. Here each lock is queued, so only the order keeps (queued)
      // below (removing) and (clearing) (#205).
      it('puts removing and clearing ahead of queued on a lock that is queued', () => {
        const { unmount } = renderCard(
          twoLocks(
            [
              back({ pushState: 'pending', pendingRemoval: true, pushRequestedAt: requestedAt, pushQueued: true }),
              // Slot 3 held its old PIN and the clear failed. It still needs its set, so it's queued too.
              front({ pushState: 'pending', pushRequestedAt: requestedAt, pushQueued: true }),
            ],
            { pushState: 'pending', pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }] },
          ),
        )
        expect(screen.getByText('Back Door (removing)')).toBeTruthy()
        expect(screen.getByText('Front Door (clearing)')).toHaveAttribute(
          'title',
          'Slot 3 may still hold the PIN, retried automatically.',
        )
        expect(screen.queryByText(/\(queued\)/)).toBeNull()
        unmount()

        // The same with the timestamps alone, for an API from before pushQueued.
        renderCard(
          twoLocks(
            [back({ slotIndex: 2 }), front({ pushState: 'pending', pushRequestedAt: requestedAt })],
            { pushState: 'pending', pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }] },
          ),
        )
        expect(screen.getByText('Front Door (clearing)')).toBeTruthy()
        expect(screen.queryByText(/\(queued\)/)).toBeNull()
      })

      it("goes by the server's pushQueued for the chip", () => {
        const sameMs = '2026-10-30T10:05:00.123Z'
        const { unmount } = renderCard(
          twoLocks(
            [
              back({ slotIndex: 2 }),
              front({
                pushState: 'pending',
                slotIndex: 4,
                schedulePending: true,
                lastPushAttemptAt: sameMs,
                pushRequestedAt: sameMs,
                pushQueued: true,
              }),
            ],
            { pushState: 'pending' },
          ),
        )
        // The schedule re-queue, 1µs after the attempt.
        expect(screen.getByText('Front Door (queued)')).toBeTruthy()
        unmount()

        renderCard(
          twoLocks([back({ slotIndex: 2 }), front({ pushState: 'pending', lastPushError: 'Lock timed out', pushRequestedAt: requestedAt, pushQueued: false })], {
            pushState: 'pending',
          }),
        )
        // Lapsed or capped.
        expect(screen.getByText('Front Door (pending)')).toHaveAttribute('title', 'Lock timed out')
      })

      it('moves from queued to on lock through the fast poll after a Retry', async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true })
        try {
          let serverCode = makeCode({ pushState: 'pending', lastPushError: '' })
          let fetches = 0
          server.use(
            http.get('/api/door-codes/', () => {
              fetches += 1
              return HttpResponse.json({ data: [serverCode] })
            }),
            http.post('/api/door-codes/7/push/', () => {
              serverCode = makeCode({
                pushState: 'pending',
                lastPushError: '',
                lockSlotAssignments: [front({ pushState: 'pending', pushRequestedAt: requestedAt })],
              })
              return HttpResponse.json({ data: serverCode })
            }),
          )

          renderWithProviders(<CardsFromQuery />)
          fireEvent.click(await screen.findByRole('button', { name: 'Retry now' }))
          expect(await screen.findByText('Front Door (queued)')).toBeTruthy()
          const fetchesAfterRetry = fetches

          serverCode = pushedCode('2026-10-30T10:05:02Z')
          await act(() => vi.advanceTimersByTimeAsync(DOOR_CODES_FAST_POLL_MS))
          await waitFor(() => expect(fetches).toBe(fetchesAfterRetry + 1))
          expect(await screen.findByText(/On lock:.*slot 3/)).toBeTruthy()
          expect(screen.queryByText(/\(queued\)/)).toBeNull()
        } finally {
          vi.useRealTimers()
        }
      })

      it.each<[string, Partial<Slot>]>([
        ['another save queues the lock again', { pushRequestedAt: '2026-10-30T10:06:00Z' }],
        ['the scheduler tries the queued push', { lastPushAttemptAt: '2026-10-30T10:05:02Z' }],
      ])('drops a Retry error once %s', async (_change, frontChange) => {
        const failedCode = (frontOverrides: Partial<Slot> = {}) =>
          twoLocks(
            [
              back({ pushState: 'failed', lastPushError: 'Lock rejected the PIN' }),
              front({ pushState: 'pending', pushRequestedAt: requestedAt, ...frontOverrides }),
            ],
            { pushState: 'failed', lastPushError: 'lock.back_door: Lock rejected the PIN' },
          )
        const readCachedCode = () => ({ code: failedCode(), dataUpdatedAt: 10 })
        server.use(http.post('/api/door-codes/7/push/', () => timeout()))

        const { rerender } = renderWithProviders(
          <CardWithRetry code={failedCode()} codesUpdatedAt={10} readCachedCode={readCachedCode} lockNameByEntityId={lockNames} />,
        )
        fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
        expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

        rerender(
          <CardWithRetry
            code={failedCode(frontChange)}
            codesUpdatedAt={20}
            readCachedCode={readCachedCode}
            lockNameByEntityId={lockNames}
          />,
        )
        expect(screen.queryByRole('alert')).toBeNull()
      })
    })

    it("drops a Retry error once a lock's own state changes, even when the code's doesn't", async () => {
      const failedCode = (frontState: Slot['pushState']) =>
        twoLocks([back({ pushState: 'failed', lastPushError: 'Lock rejected the PIN' }), front({ pushState: frontState })], {
          pushState: 'failed',
          lastPushError: 'lock.back_door: Lock rejected the PIN',
        })
      const readCachedCode = () => ({ code: failedCode('pending'), dataUpdatedAt: 10 })
      server.use(http.post('/api/door-codes/7/push/', () => timeout()))

      const { rerender } = renderWithProviders(
        <CardWithRetry
          code={failedCode('pending')}
          codesUpdatedAt={10}
          readCachedCode={readCachedCode}
          lockNameByEntityId={lockNames}
        />,
      )
      fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
      expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

      // A newer fetch with nothing new keeps it.
      rerender(
        <CardWithRetry
          code={failedCode('pending')}
          codesUpdatedAt={20}
          readCachedCode={readCachedCode}
          lockNameByEntityId={lockNames}
        />,
      )
      expect(screen.getByRole('alert')).toHaveTextContent('Lock timed out')

      // Front Door lands, the code is still failed on Back Door.
      rerender(
        <CardWithRetry
          code={failedCode('pushed')}
          codesUpdatedAt={30}
          readCachedCode={readCachedCode}
          lockNameByEntityId={lockNames}
        />,
      )
      expect(screen.queryByRole('alert')).toBeNull()
    })

    it.each<[string, (code: DoorCode) => DoorCode]>([
      ["a lock's error changes", (code) => ({ ...code, lockSlotAssignments: [code.lockSlotAssignments[0], front({ lastPushError: 'Lock is asleep' })] })],
      [
        'a lock starts being dropped',
        (code) => ({ ...code, lockSlotAssignments: [code.lockSlotAssignments[0], front({ pendingRemoval: true })] }),
      ],
      [
        'a slot on a lock is left to clear',
        (code) => ({ ...code, pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 3, removing: false }] }),
      ],
    ])('drops a Retry error once %s', async (_change, change) => {
      const failedCode = twoLocks([back({ pushState: 'failed', lastPushError: 'Lock rejected the PIN' }), front()], {
        pushState: 'failed',
        lastPushError: 'lock.back_door: Lock rejected the PIN',
      })
      const readCachedCode = () => ({ code: failedCode, dataUpdatedAt: 10 })
      server.use(http.post('/api/door-codes/7/push/', () => timeout()))

      const { rerender } = renderWithProviders(
        <CardWithRetry code={failedCode} codesUpdatedAt={10} readCachedCode={readCachedCode} lockNameByEntityId={lockNames} />,
      )
      fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
      expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

      rerender(
        <CardWithRetry
          code={change(failedCode)}
          codesUpdatedAt={20}
          readCachedCode={readCachedCode}
          lockNameByEntityId={lockNames}
        />,
      )
      expect(screen.queryByRole('alert')).toBeNull()
    })
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
      let fetches = 0
      server.use(
        http.get('/api/door-codes/', () => {
          fetches += 1
          return HttpResponse.json({ data: [serverCode] })
        }),
        http.post('/api/door-codes/7/push/', () => {
          serverCode = makeCode({ pushState: 'pending', lastPushError: '', lastPushAttemptAt: '2026-10-28T10:10:00Z' })
          return timeout()
        }),
      )

      renderWithProviders(<CardsFromQuery />)
      fireEvent.click(await screen.findByRole('button', { name: 'Retry now' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')
      await settle()
      const fetchesBeforePoll = fetches

      await nextPoll()
      await waitFor(() => expect(fetches).toBe(fetchesBeforePoll + 1))
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
