type ValidateDigitsPinOptions = {
  label: string
  required?: boolean
  minLength?: number
  maxLength?: number
}

export function validateDigitsPin(value: string, opts: ValidateDigitsPinOptions): string | null {
  const { label, required = false, minLength = 4, maxLength = 8 } = opts
  const trimmed = value.trim()
  if (!trimmed) return required ? `${label} is required` : null
  if (!/^\d+$/.test(trimmed)) return `${label} must be digits only`
  if (trimmed.length < minLength || trimmed.length > maxLength) return `${label} must be ${minLength}–${maxLength} digits`
  return null
}

export function parseOptionalTimeWindow(
  startRaw: string,
  endRaw: string
): { windowStart: string | null; windowEnd: string | null; error: string | null } {
  const windowStart = startRaw.trim() || null
  const windowEnd = endRaw.trim() || null

  if ((windowStart == null) !== (windowEnd == null)) {
    return { windowStart, windowEnd, error: 'Time window start and end must both be set.' }
  }
  if (windowStart && windowEnd && windowStart >= windowEnd) {
    return { windowStart, windowEnd, error: 'Time window end must be after start.' }
  }

  return { windowStart, windowEnd, error: null }
}

