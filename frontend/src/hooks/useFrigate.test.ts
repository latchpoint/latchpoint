import { describe, expect, it } from 'vitest'

describe('useFrigate', () => {
  it('imports', async () => {
    const mod = await import('./useFrigate')
    expect(mod).toBeTruthy()
  })
})
