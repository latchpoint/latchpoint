import { describe, expect, it } from 'vitest'

describe('tooltip', () => {
  it('imports', async () => {
    const mod = await import('./tooltip')
    expect(mod).toBeTruthy()
  })
})
