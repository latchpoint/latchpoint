import type { DoorCode } from '@/types'

/**
 * Whether a synced code can edit its active window and be turned on or off: it
 * has an end date, like one the scheduler retired at its end (#145), on or off,
 * so one turned back on isn't stuck that way (#189). Its end date can be moved
 * but not cleared. Matches DoorCodeUpdateSerializer.synced_validity_editable.
 * Every other synced code only has its label editable, the rest is the lock's.
 */
export function isSyncedValidityEditable(code: DoorCode): boolean {
  return code.source === 'synced' && code.endAt != null
}

/**
 * Whether a synced code is off for good: it's off, only lock sync can turn it
 * back on (no end date), and it has no slot on any lock, eg its slot read empty
 * and lock sync let it go. Lock sync only finds a code by the slot it's in, so
 * nothing brings this one back and deleting it is the way out. Not while a lock
 * is still being removed or having the PIN taken off, or a clear is still owed.
 */
export function isSyncedCodeStuckOff(code: DoorCode): boolean {
  if (code.source !== 'synced' || code.isActive || isSyncedValidityEditable(code)) return false
  const assignments = code.lockSlotAssignments ?? []
  if (!assignments.length || (code.pendingSlotClears ?? []).length) return false
  return assignments.every((a) => a.slotIndex == null && !a.pendingRemoval && !a.takingPinOff)
}
