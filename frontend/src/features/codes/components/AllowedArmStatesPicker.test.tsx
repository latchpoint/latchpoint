import { describe, expect, it } from 'vitest'

describe('AllowedArmStatesPicker', () => {
  it('imports', async () => {
    const mod = await import('./AllowedArmStatesPicker')
    expect(mod).toBeTruthy()
  })
})
