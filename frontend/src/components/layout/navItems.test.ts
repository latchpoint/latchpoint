import { describe, expect, it } from 'vitest'

describe('navItems', () => {
  it('imports', async () => {
    const mod = await import('./navItems')
    expect(mod).toBeTruthy()
  })
})
