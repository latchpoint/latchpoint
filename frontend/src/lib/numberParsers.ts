export function parseIntInRange(label: string, value: string, min: number, max: number): number {
  const parsed = Number.parseInt(value, 10)
  if (!Number.isFinite(parsed) || Number.isNaN(parsed)) throw new Error(`${label} must be a number.`)
  if (parsed < min || parsed > max) throw new Error(`${label} must be between ${min} and ${max}.`)
  return parsed
}

export function parseFloatInRange(label: string, value: string, min: number, max: number): number {
  const parsed = Number.parseFloat(value)
  if (!Number.isFinite(parsed) || Number.isNaN(parsed)) throw new Error(`${label} must be a number.`)
  if (parsed < min || parsed > max) throw new Error(`${label} must be between ${min} and ${max}.`)
  return parsed
}

