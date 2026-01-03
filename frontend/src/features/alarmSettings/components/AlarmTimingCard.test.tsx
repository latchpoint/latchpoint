import { describe, expect, it } from 'vitest'

describe('AlarmTimingCard', () => {
  it('imports', async () => {
    const mod = await import('./AlarmTimingCard')
    expect(mod).toBeTruthy()
  })
})
