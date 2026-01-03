import { describe, expect, it } from 'vitest'

describe('DeltaChangeControls', () => {
  it('imports', async () => {
    const mod = await import('./DeltaChangeControls')
    expect(mod).toBeTruthy()
  })
})
