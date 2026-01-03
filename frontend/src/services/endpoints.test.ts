import { describe, expect, it } from 'vitest'

describe('endpoints', () => {
  it('imports', async () => {
    const mod = await import('./endpoints')
    expect(mod).toBeTruthy()
  })
})
