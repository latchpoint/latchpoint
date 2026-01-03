import { describe, expect, it } from 'vitest'

describe('FrigateOverviewCard', () => {
  it('imports', async () => {
    const mod = await import('./FrigateOverviewCard')
    expect(mod).toBeTruthy()
  })
})
