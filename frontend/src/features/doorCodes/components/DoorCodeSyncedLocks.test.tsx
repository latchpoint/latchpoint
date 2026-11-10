// ADR 0082: a synced code's locks can be added and removed like a manual code's.
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { renderWithProviders } from '@/test/render'
import { doorCodesService } from '@/services/doorCodes'
import { DoorCodeEditContainer } from './DoorCodeEditContainer'
import type { DoorCode, Entity, UpdateDoorCodeRequest } from '@/types'

const PIN_UNKNOWN =
  "Latchpoint doesn't have a readable PIN for this code, so it can't put it on another lock. Either the lock it was synced from hides its codes or the stored PIN can't be decrypted."

// The master code lock sync imported from the Front Door.
function syncedMaster(overrides: Partial<DoorCode> = {}): DoorCode {
  return {
    id: 5,
    userId: '00000000-0000-0000-0000-000000000001',
    userDisplayName: 'Test',
    source: 'synced',
    label: 'Master',
    codeType: 'permanent',
    pin: '2468',
    pinLength: 4,
    isActive: true,
    maxUses: null,
    usesCount: 0,
    startAt: null,
    endAt: null,
    daysOfWeek: null,
    windowStart: null,
    windowEnd: null,
    validity: 'valid',
    lastUsedAt: null,
    lastUsedLock: null,
    lockAssignments: [{ id: 1, lockEntityId: 'lock.front_door' }],
    lockEntityIds: ['lock.front_door'],
    lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 1, pendingRemoval: false }],
    pendingSlotClears: [],
    pushState: 'pushed',
    lastPushAttemptAt: null,
    lastPushError: '',
    createdAt: '',
    updatedAt: '',
    ...overrides,
  }
}

function makeLock(entityId: string, name: string): Entity {
  return {
    id: entityId.length,
    entityId,
    domain: 'lock',
    name,
    deviceClass: null,
    lastState: 'locked',
    lastChanged: null,
    lastSeen: null,
    attributes: {},
    source: 'home_assistant',
    createdAt: '',
    updatedAt: '',
  }
}

const LOCKS = [makeLock('lock.front_door', 'Front Door'), makeLock('lock.back_door', 'Back Door')]

type OnUpdate = (id: number, req: UpdateDoorCodeRequest) => Promise<unknown>

function renderEditForm(code: DoorCode, onUpdate: OnUpdate = vi.fn().mockResolvedValue(undefined)) {
  renderWithProviders(
    <DoorCodeEditContainer
      code={code}
      locks={LOCKS}
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

const lockCheckbox = (entityId: string) => screen.getByRole('checkbox', { name: new RegExp(`\\(${entityId}\\)`) })

function save() {
  fireEvent.change(screen.getByLabelText(/Re-authenticate/), { target: { value: 'pw' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
}

describe('edit form for a synced code, locks', () => {
  it('enables the lock picker and keeps the PIN, schedule and active status locked', () => {
    renderEditForm(syncedMaster())

    expect(lockCheckbox('lock.front_door')).not.toBeDisabled()
    expect(lockCheckbox('lock.back_door')).not.toBeDisabled()
    expect(screen.getByLabelText('New code (optional)')).toBeDisabled()
    expect(screen.getByRole('switch', { name: 'Active' })).toBeDisabled()
    expect(screen.getByText('(Controlled by lock sync)')).toBeTruthy()
    expect(screen.queryByText('Days of week')).toBeNull()
  })

  it('says locks can be added or removed while the PIN and schedule come from the lock', () => {
    renderEditForm(syncedMaster())

    const copy = screen.getByText(/This code is synced from the lock\./).textContent ?? ''
    expect(copy).toContain('You can add or remove locks, which puts its PIN on them or takes it off.')
    expect(copy).toContain('The PIN, active status, schedule, and max uses come from the lock')
    expect(copy).not.toContain('Only the label can be edited')
    expect(copy).not.toContain('hides its codes')
  })

  it('says the same for a synced code with an end date', () => {
    renderEditForm(syncedMaster({ endAt: '2026-12-02T12:00:00Z', validity: 'valid' }))

    const copy = screen.getByText(/has an end date/).textContent ?? ''
    expect(copy).toContain('You can add or remove locks')
    expect(copy).toContain('The PIN, schedule, and max uses come from the lock')
    expect(copy).not.toContain('lock assignments')
  })

  it('sends only the added lock', async () => {
    const onUpdate = renderEditForm(syncedMaster())

    fireEvent.click(lockCheckbox('lock.back_door'))
    save()

    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
    expect(vi.mocked(onUpdate).mock.calls[0]).toEqual([5, { reauthPassword: 'pw', addLockEntityIds: ['lock.back_door'] }])
  })

  it('sends a removed lock, the one it was imported from included', async () => {
    const onUpdate = renderEditForm(
      syncedMaster({
        lockEntityIds: ['lock.back_door', 'lock.front_door'],
        lockSlotAssignments: [
          { lockEntityId: 'lock.front_door', slotIndex: 1, pendingRemoval: false },
          { lockEntityId: 'lock.back_door', slotIndex: 2, pendingRemoval: false },
        ],
      }),
    )

    fireEvent.click(lockCheckbox('lock.front_door'))
    save()

    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
    expect(vi.mocked(onUpdate).mock.calls[0][1]).toEqual({ reauthPassword: 'pw', removeLockEntityIds: ['lock.front_door'] })
  })

  it("won't save a synced code with no locks", async () => {
    const onUpdate = renderEditForm(syncedMaster())

    fireEvent.click(lockCheckbox('lock.front_door'))
    save()

    expect(await screen.findByText('Select at least one lock.')).toBeTruthy()
    expect(onUpdate).not.toHaveBeenCalled()
  })

  it('saves a new label on a synced code whose only lock is still being removed', async () => {
    const onUpdate = renderEditForm(
      syncedMaster({
        lockEntityIds: [],
        lockSlotAssignments: [{ lockEntityId: 'lock.front_door', slotIndex: 1, pendingRemoval: true }],
      }),
    )
    expect(lockCheckbox('lock.front_door')).not.toBeChecked()

    fireEvent.change(screen.getByLabelText('Label'), { target: { value: 'Old master' } })
    save()

    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
    expect(vi.mocked(onUpdate).mock.calls[0][1]).toEqual({ reauthPassword: 'pw', label: 'Old master' })
    expect(screen.queryByText('Select at least one lock.')).toBeNull()
  })

  it('says up front when the PIN is unknown', () => {
    renderEditForm(syncedMaster({ pin: null, pinLength: null }))

    expect(screen.getByText(/latchpoint doesn't know this PIN and can't put it on another lock/)).toBeTruthy()
  })

  it("shows the backend's 400 when the PIN is unknown", async () => {
    const patched = vi.fn()
    server.use(
      http.patch('/api/door-codes/5/', async ({ request }) => {
        patched(await request.json())
        return HttpResponse.json(
          { error: { status: 'validation_error', message: PIN_UNKNOWN } },
          { status: 400 },
        )
      }),
    )
    renderEditForm(syncedMaster({ pin: null, pinLength: null }), (id, req) => doorCodesService.updateDoorCode(id, req))

    fireEvent.click(lockCheckbox('lock.back_door'))
    save()

    expect(await screen.findByText(PIN_UNKNOWN)).toBeTruthy()
    expect(patched).toHaveBeenCalledWith({ reauth_password: 'pw', add_lock_entity_ids: ['lock.back_door'] })
    // The form stays open with the lock still ticked, so it can be unticked.
    expect(lockCheckbox('lock.back_door')).toBeChecked()
  })
})
