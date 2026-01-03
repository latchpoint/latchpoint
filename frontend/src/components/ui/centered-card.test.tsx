import { describe, expect, it } from 'vitest'

describe('centered-card', () => {
  it('imports', async () => {
    const mod = await import('./centered-card')
    expect(mod).toBeTruthy()
  })
})
