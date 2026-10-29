import type { DoorCode } from '@/types'

/**
 * Whether a synced code can edit its active window and be turned back on: it's
 * off and has an end date, like one the scheduler retired at its end (#145).
 * Matches DoorCodeUpdateSerializer.synced_validity_editable. Every other synced
 * code only has its label editable, the rest is the lock's.
 */
export function isSyncedValidityEditable(code: DoorCode): boolean {
  return code.source === 'synced' && !code.isActive && code.endAt != null
}
