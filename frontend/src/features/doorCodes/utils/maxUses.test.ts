import { describe, expect, it } from 'vitest'

describe('maxUses', () => {
  it('imports', async () => {
    const mod = await import('./maxUses')
    expect(mod).toBeTruthy()
  })
})
