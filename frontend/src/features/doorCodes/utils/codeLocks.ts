import type { DoorCode } from '@/types'

/**
 * Every lock the code is on, sorted, including one whose removal is still
 * waiting on its slot clear. lockEntityIds leaves those out so an API client
 * that sends it back doesn't cancel the removal (#171), and lockSlotAssignments
 * still has them with pendingRemoval, so the card and badge read both.
 */
export function codeLockEntityIds(code: DoorCode): string[] {
  const ids = new Set(code.lockEntityIds || [])
  for (const assignment of code.lockSlotAssignments || []) ids.add(assignment.lockEntityId)
  return [...ids].sort()
}

/**
 * Whether latchpoint is still taking an off synced code's PIN off one of the
 * locks added to it, after the lock it was synced from confirmed it off
 * (#221). That's a clear the scheduler and Retry still run, like a
 * pendingSlotClears entry.
 */
export function isTakingPinOff(code: DoorCode): boolean {
  return !code.isActive && (code.lockSlotAssignments || []).some((a) => !!a.takingPinOff)
}
