import { describe, expect, it } from 'vitest'

describe('badge', () => {
  it('imports', async () => {
    const mod = await import('./badge')
    expect(mod).toBeTruthy()
  })
})
