import { describe, expect, it } from 'vitest'

describe('QuickActions', () => {
  it('imports', async () => {
    const mod = await import('./QuickActions')
    expect(mod).toBeTruthy()
  })
})
