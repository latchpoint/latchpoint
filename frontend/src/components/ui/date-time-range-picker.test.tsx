import { describe, expect, it } from 'vitest'

describe('date-time-range-picker', () => {
  it('imports', async () => {
    const mod = await import('./date-time-range-picker')
    expect(mod).toBeTruthy()
  })
})
