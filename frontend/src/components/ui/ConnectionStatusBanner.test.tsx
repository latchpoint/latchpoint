import { describe, expect, it } from 'vitest'

describe('ConnectionStatusBanner', () => {
  it('imports', async () => {
    const mod = await import('./ConnectionStatusBanner')
    expect(mod).toBeTruthy()
  })
})
