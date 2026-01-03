export function formatEntitiesSyncNotice(result: { imported: number; updated: number; warnings?: string[] }): string {
  const base = `Synced entities (imported ${result.imported}, updated ${result.updated}).`
  const warnings = result.warnings ?? []
  if (warnings.length === 0) return base
  const first = warnings[0] ?? 'Unknown warning.'
  return warnings.length === 1 ? `${base} Warning: ${first}` : `${base} Warnings: ${first} (+${warnings.length - 1} more)`
}

export function formatRulesRunNotice(result: {
  evaluated: number
  fired: number
  scheduled: number
  skippedCooldown: number
  errors: number
}): string {
  return `Rules run: evaluated ${result.evaluated}, fired ${result.fired}, scheduled ${result.scheduled}, cooldown ${result.skippedCooldown}, errors ${result.errors}.`
}
