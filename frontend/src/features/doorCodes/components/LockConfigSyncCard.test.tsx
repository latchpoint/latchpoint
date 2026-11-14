import { describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { renderWithProviders } from '@/test/render'
import type { Entity, LockConfigSyncResult, LockConfigSyncSlotResult } from '@/types'
import { LockConfigSyncCard } from './LockConfigSyncCard'

const lock: Entity = {
  id: 1,
  entityId: 'lock.front_door',
  domain: 'lock',
  name: 'Front Door',
  deviceClass: null,
  lastState: 'locked',
  lastChanged: null,
  lastSeen: null,
  attributes: { zwavejs: { nodeId: 12 } },
  source: 'home_assistant',
  createdAt: '',
  updatedAt: '',
}

function slotOf(overrides: Partial<LockConfigSyncSlotResult> = {}): LockConfigSyncSlotResult {
  return {
    slotIndex: 3,
    action: 'skipped',
    doorCodeId: 7,
    pinKnown: true,
    isActive: true,
    scheduleApplied: false,
    scheduleUnsupported: false,
    schedule: null,
    warnings: [],
    error: null,
    ...overrides,
  }
}

function resultOf(slots: LockConfigSyncSlotResult[]): LockConfigSyncResult {
  return {
    lockEntityId: 'lock.front_door',
    nodeId: 12,
    created: 0,
    updated: 0,
    unchanged: 0,
    skipped: slots.length,
    deactivated: 0,
    errors: 0,
    timestamp: '2026-10-30T10:00:00Z',
    slots,
  }
}

async function syncWith(slots: LockConfigSyncSlotResult[]) {
  server.use(http.post('/api/locks/lock.front_door/sync-config/', () => HttpResponse.json({ data: resultOf(slots) })))
  renderWithProviders(<LockConfigSyncCard userId="user-1" locks={[lock]} locksIsLoading={false} locksError={null} />)
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'lock.front_door' } })
  fireEvent.change(screen.getByPlaceholderText('Re-authentication password'), { target: { value: 'pw' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sync Codes from Lock' }))
  expect(await screen.findByText('Sync Results')).toBeTruthy()
}

describe('LockConfigSyncCard', () => {
  it('labels a slot skipped because its schedule is still being applied', async () => {
    await syncWith([slotOf({ warnings: ['schedule_pending'] })])

    const chip = screen.getByText('Schedule still being applied')
    expect(chip).toHaveAttribute('title', 'schedule_pending')
    expect(screen.queryByText('schedule_pending')).toBeNull()
  })

  it('labels the other skip reasons and warnings', async () => {
    await syncWith([
      slotOf({ slotIndex: 1, warnings: ['clear_outstanding'] }),
      slotOf({ slotIndex: 2, warnings: ['inactive_code_on_lock'] }),
      slotOf({ slotIndex: 3, warnings: ['pin_mismatch'] }),
      slotOf({ slotIndex: 4, action: 'updated', warnings: ['owner_changed', 'duplicate_pin'] }),
      slotOf({ slotIndex: 5, action: 'updated', warnings: ['integrity_race'] }),
    ])

    expect(screen.getByText('Old PIN still being cleared')).toBeTruthy()
    expect(screen.getByText('Code is off, slot not cleared yet')).toBeTruthy()
    expect(screen.getByText("PIN on the lock doesn't match")).toBeTruthy()
    expect(screen.getByText('Moved to this user')).toBeTruthy()
    expect(screen.getByText('Same PIN as another door code')).toBeTruthy()
    expect(screen.getByText('Slot claimed during the sync')).toBeTruthy()
  })

  it('labels the reasons a manual code is left alone or pushed again', async () => {
    await syncWith([
      slotOf({ slotIndex: 1, warnings: ['slot_not_confirmed_empty'] }),
      slotOf({ slotIndex: 2, action: 'unchanged', warnings: ['disabled_on_lock'] }),
      slotOf({ slotIndex: 3, action: 'updated', pinKnown: null, warnings: ['slot_empty_repush'] }),
      slotOf({ slotIndex: 4, pinKnown: null, warnings: ['pin_in_another_slot'] }),
      slotOf({ slotIndex: 5, pinKnown: null, warnings: ['pin_may_be_in_hidden_slot'] }),
    ])

    expect(screen.getByText("Lock didn't confirm the slot is empty")).toHaveAttribute(
      'title',
      'slot_not_confirmed_empty',
    )
    expect(screen.getByText('Disabled at the lock')).toBeTruthy()
    expect(screen.getByText('PIN missing from the lock, sending it again')).toBeTruthy()
    expect(screen.getByText('Slot is empty but the PIN is in another slot, not sent again')).toBeTruthy()
    expect(screen.getByText('Slot is empty but the PIN may be in a slot the lock hides, not sent again')).toBeTruthy()
  })

  it('labels what happened to a synced code its other locks get a change for', async () => {
    await syncWith([
      slotOf({ slotIndex: 1, action: 'updated', warnings: ['sent_to_other_locks'] }),
      slotOf({ slotIndex: 2, action: 'unchanged', warnings: ['pin_change_unconfirmed'] }),
      slotOf({ slotIndex: 3, action: 'updated', warnings: ['pin_held_on_other_lock'] }),
      slotOf({ slotIndex: 4, action: 'unchanged', warnings: ['schedule_change_unconfirmed'] }),
      slotOf({ slotIndex: 5, warnings: ['update_pending'] }),
    ])

    expect(screen.getByText('Sending the change to the other locks')).toHaveAttribute('title', 'sent_to_other_locks')
    expect(screen.getByText("Lock didn't confirm the new PIN, keeping the old one")).toBeTruthy()
    expect(
      screen.getByText(
        'New PIN is already another code on another lock, so this code is off that lock until that code is removed',
      ),
    ).toBeTruthy()
    expect(screen.getByText("Lock didn't confirm the new schedule, keeping the old one")).toBeTruthy()
    expect(screen.getByText('Waiting for latchpoint to update this slot')).toBeTruthy()
  })

  it('labels a synced code turned off at the lock it was synced from', async () => {
    await syncWith([
      slotOf({ slotIndex: 1, action: 'updated', warnings: ['taking_off_other_locks'] }),
      slotOf({ slotIndex: 2, action: 'unchanged', warnings: ['off_change_unconfirmed'] }),
    ])

    expect(screen.getByText('Code is off, taking it off the other locks')).toHaveAttribute(
      'title',
      'taking_off_other_locks',
    )
    expect(screen.getByText("Lock didn't confirm the slot is disabled, keeping the code on")).toBeTruthy()
  })

  it('labels a slot matched back to the synced code that had its PIN (#233)', async () => {
    await syncWith([
      slotOf({ slotIndex: 1, action: 'updated', warnings: ['relinked'] }),
      slotOf({ slotIndex: 2, action: 'skipped', warnings: ['relink_not_confirmed'] }),
    ])

    expect(screen.getByText('Matched back to the code that had this PIN')).toHaveAttribute('title', 'relinked')
    expect(screen.getByText("Lock didn't confirm the PIN, not matched back to its code yet")).toBeTruthy()
  })

  it('names the door codes a duplicate PIN points at', async () => {
    await syncWith([
      slotOf({ slotIndex: 1, action: 'created', warnings: ['duplicate_pin'], duplicatePinDoorCodeIds: [12] }),
      slotOf({ slotIndex: 2, action: 'unchanged', warnings: ['duplicate_pin'], duplicatePinDoorCodeIds: [7, 9] }),
    ])

    expect(screen.getByText('Same PIN as door code #12')).toBeTruthy()
    expect(screen.getByText('Same PIN as door codes #7, #9')).toBeTruthy()
  })

  it('only says PIN saved on a slot that was saved', async () => {
    await syncWith([
      slotOf({ slotIndex: 1, action: 'skipped', pinKnown: true, warnings: ['pin_mismatch'] }),
      slotOf({ slotIndex: 2, action: 'updated', pinKnown: true }),
      slotOf({ slotIndex: 3, action: 'skipped', pinKnown: false, warnings: ['clear_outstanding'] }),
    ])

    expect(screen.getAllByText('PIN saved')).toHaveLength(1)
    expect(screen.getByText('Slot 2: updated').parentElement).toHaveTextContent('PIN saved')
    expect(screen.getByText('Slot 1: skipped').parentElement).not.toHaveTextContent('PIN saved')
    expect(screen.getByText('PIN unknown')).toBeTruthy()
  })

  it('shows a reason it has no label for as it came', async () => {
    await syncWith([slotOf({ warnings: ['something_new'] })])

    expect(screen.getByText('something_new')).toBeTruthy()
  })
})
