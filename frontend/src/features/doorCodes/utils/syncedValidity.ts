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
