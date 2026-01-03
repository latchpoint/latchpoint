import { describe, expect, it } from 'vitest'

describe('users', () => {
  it('imports', async () => {
    const mod = await import('./users')
    expect(mod).toBeTruthy()
  })
})
