import type { DoorCode } from '@/types'

export function parseOptionalMaxUses(raw: string): { value: number | null; error: string | null } {
  const trimmed = raw.trim()
  if (!trimmed) return { value: null, error: null }

  const parsed = Number(trimmed)
  if (!Number.isInteger(parsed) || parsed < 1) {
    return { value: null, error: 'Max uses must be a whole number ≥ 1.' }
  }
  return { value: parsed, error: null }
}

/**
 * How many uses a code with this max uses gets: the max uses, one for a
 * one-time code without one, else null for no limit. The backend's
 * use_limit (#145).
 */
export function limitOfUses(codeType: DoorCode['codeType'], maxUses: number | null): number | null {
  if (maxUses == null && codeType === 'one_time') return 1
  return maxUses
}

/** "Uses: N of M" when the code has a limit, else "Uses: N". */
export function usesText(code: Pick<DoorCode, 'codeType' | 'maxUses' | 'usesCount'>): string {
  const limit = limitOfUses(code.codeType, code.maxUses)
  return limit == null ? `Uses: ${code.usesCount}` : `Uses: ${code.usesCount} of ${limit}`
}
