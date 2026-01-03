import { describe, expect, it } from 'vitest'

describe('MobileNav', () => {
  it('imports', async () => {
    const mod = await import('./MobileNav')
    expect(mod).toBeTruthy()
  })
})
