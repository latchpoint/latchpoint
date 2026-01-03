import { describe, expect, it } from 'vitest'

describe('placeholder-card', () => {
  it('imports', async () => {
    const mod = await import('./placeholder-card')
    expect(mod).toBeTruthy()
  })
})
