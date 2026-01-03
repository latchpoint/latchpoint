export function parseOptionalMaxUses(raw: string): { value: number | null; error: string | null } {
  const trimmed = raw.trim()
  if (!trimmed) return { value: null, error: null }

  const parsed = Number(trimmed)
  if (!Number.isInteger(parsed) || parsed < 1) {
    return { value: null, error: 'Max uses must be a whole number ≥ 1.' }
  }
  return { value: parsed, error: null }
}

