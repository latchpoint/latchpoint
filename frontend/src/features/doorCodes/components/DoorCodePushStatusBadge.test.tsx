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

  it('shows Not on lock instead of On lock for an inactive code with no slots', () => {
    // What deactivating leaves behind: slots cleared, pushState still pushed.
    const code = makeCode({ isActive: false, pushState: 'pushed' })

    renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry
        isRetrying={false}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.getByText('Not on lock')).toBeTruthy()
    // The explanation is visible text, not only a hover title.
    expect(screen.getByText('(inactive, no slot on any of its locks)')).toBeVisible()
    expect(screen.queryByText(/^On lock/)).toBeNull()
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })

  it('shows Not on lock for an inactive pending code that never got a slot', () => {
    const code = makeCode({ isActive: false, pushState: 'pending' })

    renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry
        isRetrying={false}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.getByText('Not on lock')).toBeTruthy()
    expect(screen.queryByText('Pending sync')).toBeNull()
  })

  it('keeps Push failed without Retry for an inactive failed code with no slots', () => {
    const code = makeCode({ isActive: false, pushState: 'failed', lastPushError: 'boom' })

    renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry
        isRetrying={false}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.getByText('Push failed: boom')).toBeTruthy()
    expect(screen.getByText('(saving it as off again or deleting it retries the clear)')).toBeVisible()
    expect(screen.queryByText('Not on lock')).toBeNull()
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })

  it('does not show Not on lock when the code has no slot assignments to check', () => {
    const code = makeCode({ isActive: false, pushState: 'pushed', lockSlotAssignments: [] })

    renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry
        isRetrying={false}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.queryByText('Not on lock')).toBeNull()
    expect(screen.getByText('On lock')).toBeTruthy()
  })

  it('does not show the clear hint for an active failed code', () => {
    const code = makeCode({ pushState: 'failed', lastPushError: 'boom' })

    renderWithProviders(
      <DoorCodePushStatusBadge
        code={code}
        lockNameByEntityId={lockNames}
        canRetry
        isRetrying={false}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.queryByText(/retries the clear/)).toBeNull()
  })

  it('keeps On lock for an inactive code that still holds a slot', () => {
    const code = makeCode({
      isActive: false,
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
    expect(screen.queryByText('Not on lock')).toBeNull()
  })

  it('hides Retry for an inactive failed code that still holds a slot', () => {
    // A slot clear that failed while turning the code off.
    const code = makeCode({
      isActive: false,
      pushState: 'failed',
      lastPushError: "Couldn't clear slot 3 on lock.front_door",
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

    expect(screen.getByText(/Push failed: Couldn't clear slot 3/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })

  it('hides Retry now for an inactive pending code that still holds a slot', () => {
    const code = makeCode({
      isActive: false,
      pushState: 'pending',
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

    expect(screen.getByText('Pending sync')).toBeTruthy()
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
