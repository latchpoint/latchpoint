import { describe, expect, it } from 'vitest'

describe('user', () => {
  it('imports', async () => {
    const mod = await import('./user')
    expect(mod).toBeTruthy()
  })
})
