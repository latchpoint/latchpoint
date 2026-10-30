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

  it('shows a reason it has no label for as it came', async () => {
    await syncWith([slotOf({ warnings: ['something_new'] })])

    expect(screen.getByText('something_new')).toBeTruthy()
  })
})
