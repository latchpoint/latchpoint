// #145: a door code is only on its locks between its start and its end.
import { describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import { isDoorCodeSettling } from '@/hooks/useDoorCodesQueries'
import { DoorCodeCard } from './DoorCodeCard'
import { DoorCodeEditContainer } from './DoorCodeEditContainer'
import { DoorCodePushStatusBadge } from './DoorCodePushStatusBadge'
import type { DoorCode } from '@/types'

const START = '2026-11-01T12:00:00Z'

function makeCode(overrides: Partial<DoorCode> = {}): DoorCode {
  return {
    id: 1,
    userId: '00000000-0000-0000-0000-000000000001',
    userDisplayName: 'Test',
    source: 'manual',
    label: 'Guest',
    codeType: 'temporary',
    pin: '1357',
    pinLength: 4,
    isActive: true,
    maxUses: null,
    usesCount: 0,
    startAt: null,
    endAt: null,
    daysOfWeek: 127,
    windowStart: null,
    windowEnd: null,
    validity: 'valid',
    lastUsedAt: null,
    lastUsedLock: null,
    lockAssignments: [{ id: 1, lockEntityId: 'lock.front_door' }],
    lockEntityIds: ['lock.front_door'],
    lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: null, pendingRemoval: false }],
    pendingSlotClears: [],
    pushState: 'pending',
    lastPushAttemptAt: null,
    lastPushError: '',
    createdAt: '',
    updatedAt: '',
    ...overrides,
  }
}

const onSlot = [{ lockEntityId: 'lock.front_door', slotIndex: 2, pendingRemoval: false }]
const noSlot = [{ lockEntityId: 'lock.front_door', slotIndex: null, pendingRemoval: false }]

function renderBadge(code: DoorCode) {
  renderWithProviders(
    <DoorCodePushStatusBadge
      code={code}
      lockNameByEntityId={new Map([['lock.front_door', 'Front Door']])}
      canRetry
      isRetrying={false}
      onRetry={vi.fn()}
    />,
  )
}

function renderCard(code: DoorCode) {
  renderWithProviders(
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
      isRetryingPush={false}
      onBeginEdit={vi.fn()}
      onCloseEdit={vi.fn()}
      onUpdate={vi.fn()}
      onDelete={vi.fn()}
      onRetryPush={vi.fn()}
      codesUpdatedAt={0}
      readCachedCode={() => null}
    />,
  )
}

function renderEditForm(code: DoorCode, onUpdate = vi.fn().mockResolvedValue(undefined)) {
  renderWithProviders(
    <DoorCodeEditContainer
      code={code}
      locks={[]}
      locksIsLoading={false}
      locksError={null}
      isSaving={false}
      isDeleting={false}
      onClose={vi.fn()}
      onUpdate={onUpdate}
      onDelete={vi.fn()}
    />,
  )
  return onUpdate
}

const activeSwitch = () => screen.getByRole('switch', { name: 'Active' })

describe('push status badge', () => {
  it('shows a scheduled code waiting for its start, without Retry', () => {
    renderBadge(makeCode({ validity: 'scheduled', startAt: START, lockSlotAssignments: noSlot }))

    expect(screen.getByText('Scheduled')).toBeTruthy()
    expect(screen.getByText(`(goes on lock at ${new Date(START).toLocaleString()})`)).toBeTruthy()
    expect(screen.queryByText('Pending sync')).toBeNull()
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })

  it('says a scheduled code still on a lock is being taken off until its start', () => {
    renderBadge(makeCode({ validity: 'scheduled', startAt: START, pushState: 'pushed', lockSlotAssignments: onSlot }))

    expect(screen.getByText('Scheduled')).toBeTruthy()
    expect(screen.getByText(`(taking it off the lock until ${new Date(START).toLocaleString()})`)).toBeTruthy()
    expect(screen.queryByText(/On lock/)).toBeNull()
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })

  it('shows a scheduled code whose clear hit the attempt cap as failed, with Retry', () => {
    const onRetry = vi.fn()
    renderWithProviders(
      <DoorCodePushStatusBadge
        code={makeCode({
          validity: 'scheduled',
          startAt: START,
          pushState: 'failed',
          lastPushError: "Push gave up after 24 attempts: Couldn't clear slot 2 on lock.front_door",
          lockSlotAssignments: onSlot,
          pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 2, removing: false }],
        })}
        lockNameByEntityId={new Map([['lock.front_door', 'Front Door']])}
        canRetry
        isRetrying={false}
        onRetry={onRetry}
      />,
    )

    expect(screen.getByText(/^Clear failed/)).toBeTruthy()
    expect(screen.queryByText(/taking it off/)).toBeNull()
    expect(screen.queryByText(/goes on/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('says its locks for a scheduled or expired code on more than one lock', () => {
    const twoLocks = {
      lockEntityIds: ['lock.front_door', 'lock.back_door'],
      lockAssignments: [
        { id: 1, lockEntityId: 'lock.front_door' },
        { id: 2, lockEntityId: 'lock.back_door' },
      ],
    }
    const startsAt = new Date(START).toLocaleString()
    renderBadge(makeCode({ ...twoLocks, validity: 'scheduled', startAt: START, pushState: 'pushed', lockSlotAssignments: onSlot }))
    expect(screen.getByText(`(taking it off its locks until ${startsAt})`)).toBeTruthy()
    cleanup()

    renderBadge(makeCode({ ...twoLocks, validity: 'scheduled', startAt: START, lockSlotAssignments: noSlot }))
    expect(screen.getByText(`(goes on its locks at ${startsAt})`)).toBeTruthy()
    cleanup()

    renderBadge(makeCode({ ...twoLocks, validity: 'expired', pushState: 'pushed', lockSlotAssignments: onSlot }))
    expect(screen.getByText('(removing from its locks)')).toBeTruthy()
  })

  it('shows an expired code that is still on as being removed, without Retry', () => {
    renderBadge(makeCode({ validity: 'expired', pushState: 'pushed', lockSlotAssignments: onSlot }))

    expect(screen.getByText('Expired')).toBeTruthy()
    expect(screen.getByText('(removing from lock)')).toBeTruthy()
    expect(screen.queryByText(/On lock/)).toBeNull()
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })

  it('falls back to the clear states once an expired code is off', () => {
    renderBadge(
      makeCode({
        validity: 'expired',
        isActive: false,
        pushState: 'pending',
        lockSlotAssignments: onSlot,
        pendingSlotClears: [{ lockEntityId: 'lock.front_door', slotIndex: 2, removing: false }],
      }),
    )

    expect(screen.getByText('Pending clear')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Retry now' })).toBeTruthy()
    expect(screen.queryByText('(removing from lock)')).toBeNull()
  })

  it('shows an expired code that is off and cleared as not on the lock', () => {
    renderBadge(makeCode({ validity: 'expired', isActive: false, pushState: 'pushed', lockSlotAssignments: noSlot }))

    expect(screen.getByText('Not on lock')).toBeTruthy()
  })

  it('keeps the existing states for a valid code', () => {
    renderBadge(makeCode({ validity: 'valid', pushState: 'pushed', lockSlotAssignments: onSlot }))

    expect(screen.getByText(/On lock:.*Front Door.*slot 2/)).toBeTruthy()
    expect(screen.queryByText('Scheduled')).toBeNull()
  })
})

describe('card', () => {
  it('says why an expired code is off', () => {
    renderCard(makeCode({ validity: 'expired', isActive: false, pushState: 'pushed', lockSlotAssignments: noSlot }))

    expect(screen.getByText('Inactive')).toBeTruthy()
    expect(screen.getByText('Expired')).toBeTruthy()
  })

  it("says max uses isn't enforced on a code that has one", () => {
    renderCard(makeCode({ maxUses: 3 }))

    expect(screen.getByText(/Max uses: 3/)).toBeTruthy()
    expect(screen.getByText("Max uses isn't enforced yet")).toBeTruthy()
  })

  it("doesn't mention max uses on a code without one", () => {
    renderCard(makeCode())

    expect(screen.queryByText(/Max uses/)).toBeNull()
  })
})

describe('edit form', () => {
  const expiredOff = () =>
    makeCode({
      validity: 'expired',
      isActive: false,
      pushState: 'pushed',
      startAt: '2026-10-01T12:00:00Z',
      endAt: '2026-10-02T12:00:00Z',
    })

  it('hides max uses', () => {
    renderEditForm(makeCode({ maxUses: 3 }))

    expect(screen.queryByLabelText('Max uses (optional)')).toBeNull()
  })

  it("won't turn an expired code back on and says why", () => {
    renderEditForm(expiredOff())

    expect(activeSwitch()).toBeDisabled()
    expect(screen.getByText('(Expired, set a later end for the active window to turn it on)')).toBeTruthy()
  })

  it('keeps the toggle disabled when the end is edited but still in the past', () => {
    renderEditForm(expiredOff())

    // Move the end's time within the same past day.
    fireEvent.click(screen.getByRole('button', { name: /→/ }))
    const untilInput = screen.getByText('Until').parentElement!.querySelector('input')!
    const edited = untilInput.value === '01:00' ? '02:00' : '01:00'
    fireEvent.change(untilInput, { target: { value: edited } })
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.getByRole('button', { name: /→/ }).textContent).toMatch(/[12]:00/)

    expect(activeSwitch()).toBeDisabled()
    expect(screen.getByText('(Expired, set a later end for the active window to turn it on)')).toBeTruthy()
  })

  it('lets the code be turned on once the end date is moved off the past', async () => {
    const onUpdate = renderEditForm(expiredOff())

    // Clear the range in the picker, so the code has no end.
    fireEvent.click(screen.getByRole('button', { name: /→/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))

    expect(activeSwitch()).not.toBeDisabled()
    fireEvent.click(activeSwitch())
    fireEvent.change(screen.getByLabelText(/Re-authenticate/), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
    expect(onUpdate.mock.calls[0][1]).toMatchObject({ isActive: true, startAt: null, endAt: null })
  })

  it('lets an expired code that is still on be turned off', () => {
    renderEditForm(makeCode({ validity: 'expired', isActive: true, endAt: '2026-10-02T12:00:00Z' }))

    expect(activeSwitch()).not.toBeDisabled()
    fireEvent.click(activeSwitch())
    expect(activeSwitch()).toHaveAttribute('aria-checked', 'false')
  })

  it('leaves the toggle alone for a code that is not expired', () => {
    renderEditForm(makeCode({ isActive: false, pushState: 'pushed' }))

    expect(activeSwitch()).not.toBeDisabled()
    expect(screen.queryByText(/Expired/)).toBeNull()
  })

  // #184: the API takes dates on one-time codes, so one retired at its end
  // needs its active window on the form to come back on.
  const expiredOneTime = () =>
    makeCode({
      ...expiredOff(),
      codeType: 'one_time',
      daysOfWeek: null,
    })

  it('shows the active window for a one-time code, without the schedule', () => {
    renderEditForm(expiredOneTime())

    expect(screen.getByText('Active date range (optional)')).toBeTruthy()
    expect(screen.getByRole('button', { name: /→/ })).not.toBeDisabled()
    expect(screen.queryByText('Days of week')).toBeNull()
    expect(activeSwitch()).toBeDisabled()
  })

  it('lets an expired one-time code be turned back on by changing its window', async () => {
    const onUpdate = renderEditForm(expiredOneTime())

    fireEvent.click(screen.getByRole('button', { name: /→/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))

    expect(activeSwitch()).not.toBeDisabled()
    fireEvent.click(activeSwitch())
    fireEvent.change(screen.getByLabelText(/Re-authenticate/), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
    expect(onUpdate.mock.calls[0][1]).toEqual({ reauthPassword: 'pw', isActive: true, startAt: null, endAt: null })
  })
})

describe('edit form for a synced code', () => {
  // Lock sync made it permanent and kept its dates, then the scheduler retired it.
  const retiredSynced = () =>
    makeCode({
      source: 'synced',
      codeType: 'permanent',
      validity: 'expired',
      isActive: false,
      pushState: 'pushed',
      startAt: '2026-10-01T12:00:00Z',
      endAt: '2026-10-02T12:00:00Z',
    })

  it('shows the active window and lets a retired synced code be turned back on', async () => {
    // Its stored end is in the past. The clock is put before it so moving the
    // end's time counts as a later end, without picking a day in the calendar.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-01T12:00:00Z'))
    try {
      const onUpdate = renderEditForm(retiredSynced())

      expect(screen.getByText(/Its active window can be changed \(but not cleared\) and it can be turned on or off/)).toBeTruthy()
      // Its schedule is still the lock's.
      expect(screen.queryByText('Days of week')).toBeNull()
      expect(activeSwitch()).toBeDisabled()
      expect(screen.getByText('(Expired, set a later end for the active window to turn it on)')).toBeTruthy()

      fireEvent.click(screen.getByRole('button', { name: /→/ }))
      const untilInput = screen.getByText('Until').parentElement!.querySelector('input')!
      fireEvent.change(untilInput, { target: { value: untilInput.value === '01:00' ? '02:00' : '01:00' } })
      fireEvent.click(screen.getByRole('button', { name: 'Done' }))

      expect(activeSwitch()).not.toBeDisabled()
      fireEvent.click(activeSwitch())
      fireEvent.change(screen.getByLabelText(/Re-authenticate/), { target: { value: 'pw' } })
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))

      await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
      const req = onUpdate.mock.calls[0][1]
      expect(req).toEqual({ reauthPassword: 'pw', isActive: true, startAt: expect.any(String), endAt: expect.any(String) })
    } finally {
      vi.useRealTimers()
    }
  })

  it("won't save a synced code with its end date cleared", async () => {
    // #189: without an end date it would be stuck however it was left.
    const onUpdate = renderEditForm(retiredSynced())

    fireEvent.click(screen.getByRole('button', { name: /→/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    fireEvent.click(activeSwitch())
    fireEvent.change(screen.getByLabelText(/Re-authenticate/), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText("A synced code's active window needs an end.")).toBeTruthy()
    expect(onUpdate).not.toHaveBeenCalled()
  })

  it('only sends the label for a retired synced code when nothing else changed', async () => {
    const onUpdate = renderEditForm(retiredSynced())

    fireEvent.change(screen.getByLabelText(/Re-authenticate/), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
    expect(onUpdate.mock.calls[0][1]).toEqual({ reauthPassword: 'pw' })
  })

  it('lets an active synced code with an end date be turned off', async () => {
    // #189: once it's back on it isn't stuck on, even while it waits on its start.
    const onUpdate = renderEditForm(
      makeCode({
        source: 'synced',
        codeType: 'temporary',
        validity: 'scheduled',
        startAt: '2026-12-01T12:00:00Z',
        endAt: '2026-12-02T12:00:00Z',
      }),
    )
    expect(activeSwitch()).not.toBeDisabled()
    expect(screen.queryByText('(Controlled by lock sync)')).toBeNull()
    expect(screen.getByRole('button', { name: /→/ })).not.toBeDisabled()

    fireEvent.click(activeSwitch())
    fireEvent.change(screen.getByLabelText(/Re-authenticate/), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
    expect(onUpdate.mock.calls[0][1]).toEqual({ reauthPassword: 'pw', isActive: false })
  })

  it('keeps a synced code without an end date controlled by lock sync', () => {
    renderEditForm(makeCode({ source: 'synced', codeType: 'temporary' }))
    expect(activeSwitch()).toBeDisabled()
    expect(screen.getByText('(Controlled by lock sync)')).toBeTruthy()
    cleanup()

    renderEditForm(makeCode({ source: 'synced', codeType: 'permanent', isActive: false, pushState: 'pushed' }))
    expect(activeSwitch()).toBeDisabled()
    expect(screen.getByText('(Controlled by lock sync)')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /→|Select date range/ })).toBeNull()
  })
})

describe('isDoorCodeSettling', () => {
  it("doesn't poll for a scheduled code, which only waits on the clock", () => {
    expect(isDoorCodeSettling(makeCode({ validity: 'scheduled', lockSlotAssignments: noSlot }))).toBe(false)
  })

  it('polls while a scheduled code still holds a slot, until the withdraw takes it off', () => {
    expect(isDoorCodeSettling(makeCode({ validity: 'scheduled', pushState: 'pushed', lockSlotAssignments: onSlot }))).toBe(
      true,
    )
    expect(isDoorCodeSettling(makeCode({ validity: 'scheduled', pushState: 'pending', lockSlotAssignments: noSlot }))).toBe(
      false,
    )
  })

  it("doesn't poll for a scheduled code whose clear hit the attempt cap, which only Retry moves", () => {
    const clear = { lockEntityId: 'lock.front_door', slotIndex: 2, removing: false }
    expect(
      isDoorCodeSettling(
        makeCode({ validity: 'scheduled', pushState: 'failed', lockSlotAssignments: onSlot, pendingSlotClears: [clear] }),
      ),
    ).toBe(false)
  })

  it('polls while a scheduled code still has a slot to clear', () => {
    const clear = { lockEntityId: 'lock.front_door', slotIndex: 2, removing: false }
    expect(isDoorCodeSettling(makeCode({ validity: 'scheduled', pendingSlotClears: [clear] }))).toBe(true)
  })

  it('polls while an expired code is still on, whatever its push state', () => {
    expect(isDoorCodeSettling(makeCode({ validity: 'expired', pushState: 'pushed', lockSlotAssignments: onSlot }))).toBe(
      true,
    )
    expect(isDoorCodeSettling(makeCode({ validity: 'expired', pushState: 'failed' }))).toBe(true)
  })

  it("doesn't poll for an expired code that's off and cleared", () => {
    expect(
      isDoorCodeSettling(makeCode({ validity: 'expired', isActive: false, pushState: 'pushed', lockSlotAssignments: noSlot })),
    ).toBe(false)
  })
})
