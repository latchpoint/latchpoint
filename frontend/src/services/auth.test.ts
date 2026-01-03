import { describe, expect, it } from 'vitest'

describe('auth', () => {
  it('imports', async () => {
    const mod = await import('./auth')
    expect(mod).toBeTruthy()
  })
})
