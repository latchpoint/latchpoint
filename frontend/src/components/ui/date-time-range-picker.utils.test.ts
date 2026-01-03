import { describe, expect, it } from 'vitest'
import {
  getTimePart,
  parseLocalDateTime,
  withDatePreserveTime,
  withTimePreserveDate,
} from '@/components/ui/date-time-range-picker.utils'

describe('date-time-range-picker.utils', () => {
  it('parseLocalDateTime returns null for empty/invalid', () => {
    expect(parseLocalDateTime('')).toBeNull()
    expect(parseLocalDateTime('nope')).toBeNull()
  })

  it('getTimePart extracts time or fallback', () => {
    expect(getTimePart('2025-01-01T12:34', '00:00')).toBe('12:34')
    expect(getTimePart('2025-01-01', '00:00')).toBe('00:00')
  })

  it('withDatePreserveTime keeps existing time or uses fallback', () => {
    const date = new Date(2025, 0, 2)
    expect(withDatePreserveTime('2025-01-01T12:34', date, '00:00')).toMatch(/2025-01-02T12:34/)
    expect(withDatePreserveTime('', date, '09:00')).toMatch(/2025-01-02T09:00/)
  })

  it('withTimePreserveDate returns empty for invalid existing', () => {
    expect(withTimePreserveDate('', '12:00')).toBe('')
  })
})
