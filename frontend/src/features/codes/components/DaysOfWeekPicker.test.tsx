import { describe, expect, it } from 'vitest'

describe('DaysOfWeekPicker', () => {
  it('imports', async () => {
    const mod = await import('./DaysOfWeekPicker')
    expect(mod).toBeTruthy()
  })
})
