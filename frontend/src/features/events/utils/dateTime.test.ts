import { describe, expect, it } from 'vitest'
import { formatEventTimeAbsolute, formatEventTimeRelative, toUtcIsoFromDatetimeLocal } from '@/features/events/utils/dateTime'

describe('events/dateTime', () => {
  it('toUtcIsoFromDatetimeLocal returns null for empty/invalid', () => {
    expect(toUtcIsoFromDatetimeLocal('')).toBeNull()
    expect(toUtcIsoFromDatetimeLocal('   ')).toBeNull()
    expect(toUtcIsoFromDatetimeLocal('not a date')).toBeNull()
  })

  it('toUtcIsoFromDatetimeLocal returns ISO string for valid local datetime', () => {
    const iso = toUtcIsoFromDatetimeLocal('2025-01-01T00:00')
    expect(iso).toMatch(/2025-01-01T/)
    expect(iso).toMatch(/Z$/)
  })

  it('formatEventTimeRelative falls back to input on invalid timestamps', () => {
    expect(formatEventTimeRelative('not a timestamp')).toBe('not a timestamp')
  })

  it('formatEventTimeAbsolute returns a string', () => {
    expect(typeof formatEventTimeAbsolute('2025-01-01T00:00:00Z')).toBe('string')
  })
})
