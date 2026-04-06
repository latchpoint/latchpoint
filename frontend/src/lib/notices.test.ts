import { describe, expect, it } from 'vitest'
import { formatRulesRunNotice } from './notices'

describe('notices', () => {
  it('imports', async () => {
    const mod = await import('./notices')
    expect(mod).toBeTruthy()
  })
})

describe('formatRulesRunNotice', () => {
  it('formats basic result without stopped rules', () => {
    const result = formatRulesRunNotice({
      evaluated: 5,
      fired: 2,
      scheduled: 1,
      skippedCooldown: 0,
      skippedStopped: 0,
      errors: 0,
    })
    expect(result).toBe('Rules run: evaluated 5, fired 2, scheduled 1, cooldown 0, errors 0.')
  })

  it('includes stopped count when skippedStopped > 0', () => {
    const result = formatRulesRunNotice({
      evaluated: 3,
      fired: 1,
      scheduled: 0,
      skippedCooldown: 0,
      skippedStopped: 2,
      errors: 0,
    })
    expect(result).toBe('Rules run: evaluated 3, fired 1, scheduled 0, cooldown 0, stopped 2, errors 0.')
  })

  it('omits stopped when skippedStopped is 0', () => {
    const result = formatRulesRunNotice({
      evaluated: 10,
      fired: 5,
      scheduled: 2,
      skippedCooldown: 1,
      skippedStopped: 0,
      errors: 1,
    })
    expect(result).not.toContain('stopped')
    expect(result).toBe('Rules run: evaluated 10, fired 5, scheduled 2, cooldown 1, errors 1.')
  })

  it('includes both cooldown and stopped when both present', () => {
    const result = formatRulesRunNotice({
      evaluated: 8,
      fired: 3,
      scheduled: 1,
      skippedCooldown: 2,
      skippedStopped: 1,
      errors: 0,
    })
    expect(result).toContain('cooldown 2')
    expect(result).toContain('stopped 1')
    expect(result).toBe('Rules run: evaluated 8, fired 3, scheduled 1, cooldown 2, stopped 1, errors 0.')
  })

  it('stopped appears before errors in the output', () => {
    const result = formatRulesRunNotice({
      evaluated: 1,
      fired: 0,
      scheduled: 0,
      skippedCooldown: 0,
      skippedStopped: 1,
      errors: 1,
    })
    const stoppedIndex = result.indexOf('stopped')
    const errorsIndex = result.indexOf('errors')
    expect(stoppedIndex).toBeLessThan(errorsIndex)
  })
})
