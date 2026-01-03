import { describe, expect, it } from 'vitest'
import { daysMaskToSet, daysSetToMask, formatDaysMask } from '@/features/codes/utils/daysOfWeek'

describe('daysOfWeek utils', () => {
  it('converts mask to set and back', () => {
    const mask = 0b0101010
    const set = daysMaskToSet(mask)
    expect(daysSetToMask(set)).toBe(mask)
  })

  it('formats common masks', () => {
    expect(formatDaysMask(127)).toBe('Every day')
    expect(formatDaysMask(0)).toBe('No days')
    expect(formatDaysMask(1)).toMatch(/Mon/)
  })
})

