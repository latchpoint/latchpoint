import { describe, expect, it, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import { DoorCodePushStatusBadge } from './DoorCodePushStatusBadge'
import type { DoorCode } from '@/types'

function makeCode(overrides: Partial<DoorCode> = {}): DoorCode {
  return {
    id: 1,
    userId: '00000000-0000-0000-0000-000000000001',
    userDisplayName: 'Test',
    source: 'manual',
    label: 'Test',
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
    pushState: 'pending',
    lastPushAttemptAt: null,
    lastPushError: '',
    createdAt: '',
    updatedAt: '',
    ...overrides,
  }
}

describe('DoorCodePushStatusBadge', () => {
  const lockNames = new Map([['lock.front_door', 'Front Door']])

  it('renders pushed state with slot label', () => {
    const code = makeCode({
      pushState: 'pushed',
      lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 3 }],
    })

    renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry
        isRetrying={false}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.getByText(/On lock:.*Front Door.*slot 3/)).toBeTruthy()
  })

  it('renders failed state with error message and retry button', () => {
    const onRetry = vi.fn()
    const code = makeCode({
      pushState: 'failed',
      lastPushError: 'Gateway timeout after 5.0s',
    })

    renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry
        isRetrying={false}
        onRetry={onRetry}
      />,
    )

    expect(screen.getByText(/Push failed: Gateway timeout/)).toBeTruthy()
    const retry = screen.getByRole('button', { name: /^Retry$/ })
    fireEvent.click(retry)
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('renders pending state with retry button when allowed', () => {
    const onRetry = vi.fn()
    const code = makeCode({ pushState: 'pending' })

    renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry
        isRetrying={false}
        onRetry={onRetry}
      />,
    )

    expect(screen.getByText('Pending sync')).toBeTruthy()
    const retry = screen.getByRole('button', { name: /Retry now/ })
    fireEvent.click(retry)
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('disables the retry button while retrying', () => {
    const onRetry = vi.fn()
    const code = makeCode({ pushState: 'failed', lastPushError: 'boom' })

    renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry
        isRetrying
        onRetry={onRetry}
      />,
    )

    const retry = screen.getByRole('button', { name: /Retrying/ })
    expect((retry as HTMLButtonElement).disabled).toBe(true)
  })

  it('hides retry button when canRetry is false', () => {
    const code = makeCode({ pushState: 'failed', lastPushError: 'boom' })

    renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry={false}
        isRetrying={false}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })

  it('renders nothing when the code has no lock assignments', () => {
    const code = makeCode({ lockEntityIds: [], lockAssignments: [], lockSlotAssignments: [] })

    const { container } = renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry
        isRetrying={false}
        onRetry={vi.fn()}
      />,
    )

    expect(container.firstChild).toBeNull()
  })
})
