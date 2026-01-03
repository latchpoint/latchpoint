import { describe, expect, it } from 'vitest'

describe('card', () => {
  it('imports', async () => {
    const mod = await import('./card')
    expect(mod).toBeTruthy()
  })
})
