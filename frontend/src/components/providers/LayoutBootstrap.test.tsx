import { describe, expect, it } from 'vitest'

describe('LayoutBootstrap', () => {
  it('imports', async () => {
    const mod = await import('./LayoutBootstrap')
    expect(mod).toBeTruthy()
  })
})
