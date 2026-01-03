import { describe, expect, it } from 'vitest'

describe('HaTargetEntityIdsPicker', () => {
  it('imports', async () => {
    const mod = await import('./HaTargetEntityIdsPicker')
    expect(mod).toBeTruthy()
  })
})
