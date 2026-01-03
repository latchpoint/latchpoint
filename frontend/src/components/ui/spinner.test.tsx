import { describe, expect, it } from 'vitest'

describe('spinner', () => {
  it('imports', async () => {
    const mod = await import('./spinner')
    expect(mod).toBeTruthy()
  })
})
