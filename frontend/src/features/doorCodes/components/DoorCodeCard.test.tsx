import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { renderWithProviders } from '@/test/render'
import { useRetryDoorCodePushMutation } from '@/hooks/useDoorCodesQueries'
import { DoorCodeCard } from './DoorCodeCard'
import type { DoorCode } from '@/types'

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
    lastPushAttemptAt: null,
    createdAt: '',
    updatedAt: '',
    ...overrides,
  }
}

// Wires the card to the real Retry mutation the way DoorCodesPage does.
function CardWithRetry({ code }: { code: DoorCode }) {
  const retryPushMutation = useRetryDoorCodePushMutation(code.userId)
  return (
    <DoorCodeCard
      code={code}
      canManage
      isEditing={false}
      lockNameByEntityId={new Map([['lock.front_door', 'Front Door']])}
      locks={[]}
      locksIsLoading={false}
      locksError={null}
      isSaving={false}
      isDeleting={false}
      isRetryingPush={retryPushMutation.isPending}
      onBeginEdit={vi.fn()}
      onCloseEdit={vi.fn()}
      onUpdate={vi.fn()}
      onDelete={vi.fn()}
      onRetryPush={(id) => retryPushMutation.mutateAsync(id)}
    />
  )
}

describe('DoorCodeCard', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeCard')
    expect(mod).toBeTruthy()
  })

  it('shows the error when Retry is refused', async () => {
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

    renderWithProviders(<CardWithRetry code={makeCode()} />)
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Door code is inactive. Turn it on before pushing it to its locks.',
    )
  })

  it('shows the status text when Retry fails without an error body', async () => {
    server.use(http.post('/api/door-codes/7/push/', () => new HttpResponse(null, { status: 502 })))

    renderWithProviders(<CardWithRetry code={makeCode()} />)
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Bad Gateway')
  })

  it('clears the error when Retry is clicked again and works', async () => {
    let calls = 0
    server.use(
      http.post('/api/door-codes/7/push/', () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ error: { status: 'timeout', message: 'Lock timed out' } }, { status: 504 })
        }
        return HttpResponse.json({ data: makeCode({ pushState: 'pending', lastPushError: '' }) })
      }),
    )

    renderWithProviders(<CardWithRetry code={makeCode()} />)
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Lock timed out')

    fireEvent.click(await screen.findByRole('button', { name: /^Retry$/ }))
    await vi.waitFor(() => expect(calls).toBe(2))
    await vi.waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  })

  it('does not offer Retry for an inactive code', () => {
    renderWithProviders(<CardWithRetry code={makeCode({ isActive: false })} />)

    expect(screen.getByText('Inactive')).toBeTruthy()
    expect(screen.getByText('Removed from lock')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })
})
