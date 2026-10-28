import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { renderWithProviders } from '@/test/render'
import { useDoorCodesQuery, useRetryDoorCodePushMutation } from '@/hooks/useDoorCodesQueries'
import { DoorCodeCard } from './DoorCodeCard'
import type { DoorCode } from '@/types'

const INACTIVE_MESSAGE = 'Door code is inactive. Turn it on before pushing it to its locks.'

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
    lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: null }],
    pushState: 'failed',
    lastPushError: 'Gateway timeout after 5.0s',
    lastPushAttemptAt: '2026-10-28T10:00:00Z',
    createdAt: '',
    updatedAt: '',
    ...overrides,
  }
}

function conflict() {
  return HttpResponse.json({ error: { status: 'conflict', message: INACTIVE_MESSAGE } }, { status: 409 })
}

function card(code: DoorCode, retry: ReturnType<typeof useRetryDoorCodePushMutation>) {
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
    />
  )
}

// The card wired to the real Retry mutation, with the code passed in so tests
// can rerender it with the state a later refetch would bring.
function CardWithRetry({ code }: { code: DoorCode }) {
  const retry = useRetryDoorCodePushMutation(code.userId)
  return card(code, retry)
}

// The card fed from the real door codes query, the way DoorCodesPage does it.
function CardsFromQuery({ userId }: { userId: string }) {
  const codesQuery = useDoorCodesQuery({ userId, isAdmin: true })
  const retry = useRetryDoorCodePushMutation(userId)
  return <>{(codesQuery.data || []).map((code) => card(code, retry))}</>
}

describe('DoorCodeCard', () => {
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
        const message = calls === 1 ? 'Lock timed out' : 'Lock is still asleep'
        return HttpResponse.json({ error: { status: 'timeout', message } }, { status: 504 })
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
    let release: () => void = () => {}
    const secondCallReleased = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.post('/api/door-codes/7/push/', async () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ error: { status: 'timeout', message: 'Lock timed out' } }, { status: 504 })
        }
        await secondCallReleased
        return HttpResponse.json({ data: makeCode({ pushState: 'pending', lastPushError: '' }) })
      }),
    )

    renderWithProviders(<CardWithRetry code={makeCode()} />)
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByRole('button', { name: /Retrying/ })).toBeDisabled()
    release()

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

    const { queryClient } = renderWithProviders(<CardsFromQuery userId={serverCode.userId} />)
    fireEvent.click(await screen.findByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByText('Not on lock')).toBeTruthy()
    expect(await screen.findByRole('alert')).toHaveTextContent(INACTIVE_MESSAGE)

    // A refetch with nothing new keeps the error.
    await queryClient.invalidateQueries()
    expect(screen.getByRole('alert')).toHaveTextContent(INACTIVE_MESSAGE)

    // Someone turns it back on and it lands on the lock.
    serverCode = makeCode({
      pushState: 'pushed',
      lastPushError: '',
      lastPushAttemptAt: '2026-10-28T10:05:00Z',
      lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 3 }],
    })
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
        return HttpResponse.json({ error: { status: 'timeout', message: 'Lock timed out' } }, { status: 504 })
      }),
    )

    const { queryClient } = renderWithProviders(<CardsFromQuery userId={serverCode.userId} />)
    fireEvent.click(await screen.findByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

    await queryClient.invalidateQueries()
    expect(screen.getByRole('alert')).toHaveTextContent('Lock timed out')

    serverCode = makeCode({
      pushState: 'pushed',
      lastPushError: '',
      lastPushAttemptAt: '2026-10-28T10:15:00Z',
      lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 3 }],
    })
    await queryClient.invalidateQueries()

    expect(await screen.findByText(/On lock:.*Front Door.*slot 3/)).toBeTruthy()
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

    renderWithProviders(<CardsFromQuery userId={serverCode.userId} />)
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
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(screen.getByRole('alert')).toHaveTextContent(INACTIVE_MESSAGE)
  })

  it('does not offer Retry for an inactive code', () => {
    renderWithProviders(<CardWithRetry code={makeCode({ isActive: false, pushState: 'pushed' })} />)

    expect(screen.getByText('Inactive')).toBeTruthy()
    expect(screen.getByText('Not on lock')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })
})
