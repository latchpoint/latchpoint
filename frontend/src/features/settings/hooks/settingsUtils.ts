/**
 * Shared utilities for integration settings model hooks.
 *
 * Extracts common patterns: splitting masked flags from values,
 * and shallow-comparing drafts for dirty detection.
 */

/**
 * Split an API response into masked boolean flags (has_*) and regular values.
 * Masked flags are used to indicate whether an encrypted field has a saved value.
 */
export function splitMaskedFlags(
  data: Record<string, unknown> | undefined | null
): { values: Record<string, unknown> | null; maskedFlags: Record<string, boolean> } {
  if (!data) return { values: null, maskedFlags: {} }

  const values: Record<string, unknown> = {}
  const maskedFlags: Record<string, boolean> = {}

  for (const [key, value] of Object.entries(data)) {
    if (key.startsWith('has') && typeof value === 'boolean') {
      maskedFlags[key] = value
    } else {
      values[key] = value
    }
  }

  return { values, maskedFlags }
}

/**
 * Shallow-compare two Record objects for equality.
 * More robust than JSON.stringify — not sensitive to key ordering.
 */
export function shallowEqual(
  a: Record<string, unknown> | null | undefined,
  b: Record<string, unknown> | null | undefined
): boolean {
  if (a === b) return true
  if (!a || !b) return false
  const keysA = Object.keys(a)
  const keysB = Object.keys(b)
  if (keysA.length !== keysB.length) return false
  return keysA.every((k) => a[k] === b[k])
}
