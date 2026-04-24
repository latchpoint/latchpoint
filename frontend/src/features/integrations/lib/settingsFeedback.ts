import { isRecord } from '@/lib/typeGuards'

export type SettingsErrorCategory =
  | 'validation'
  | 'auth'
  | 'network'
  | 'server'
  | 'unknown'

export interface CategorizedError {
  category: SettingsErrorCategory
  message: string
}

export type SettingsActionVerb = 'Save' | 'Refresh'

export function categorizeSettingsError(
  err: unknown,
  verbPrefix: SettingsActionVerb
): CategorizedError {
  if (isRecord(err) && err.code === '400' && isRecord(err.details)) {
    const firstKey = Object.keys(err.details)[0]
    const raw = err.details[firstKey]
    const firstMsg = Array.isArray(raw) && typeof raw[0] === 'string' ? raw[0] : 'invalid'
    return {
      category: 'validation',
      message: `${verbPrefix} failed: ${firstKey} — ${firstMsg}`,
    }
  }
  if (isRecord(err) && (err.code === '401' || err.code === '403')) {
    return {
      category: 'auth',
      message: `${verbPrefix} failed: you don't have permission to change these settings.`,
    }
  }
  if (err instanceof TypeError) {
    return {
      category: 'network',
      message: `${verbPrefix} failed: could not reach the server. Check your connection and try again.`,
    }
  }
  return {
    category: 'unknown',
    message: `${verbPrefix} failed: ${String(err)}`,
  }
}
