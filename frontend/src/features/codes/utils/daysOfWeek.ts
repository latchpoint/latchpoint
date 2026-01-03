export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const

export function daysMaskToSet(mask: number): Set<number> {
  const out = new Set<number>()
  for (let i = 0; i < 7; i += 1) {
    if ((mask & (1 << i)) !== 0) out.add(i)
  }
  return out
}

export function daysSetToMask(days: Set<number>): number {
  let mask = 0
  for (const day of days) mask |= 1 << day
  return mask
}

export function formatDaysMask(mask: number): string {
  if (mask === 127) return 'Every day'
  const names: string[] = []
  for (let i = 0; i < 7; i += 1) {
    if ((mask & (1 << i)) !== 0) names.push(DAY_LABELS[i])
  }
  return names.length ? names.join(', ') : 'No days'
}

