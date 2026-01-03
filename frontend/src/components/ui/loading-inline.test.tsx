import { describe, expect, it } from 'vitest'

describe('loading-inline', () => {
  it('imports', async () => {
    const mod = await import('./loading-inline')
    expect(mod).toBeTruthy()
  })
})
