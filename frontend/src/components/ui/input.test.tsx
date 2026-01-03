import { describe, expect, it } from 'vitest'

describe('input', () => {
  it('imports', async () => {
    const mod = await import('./input')
    expect(mod).toBeTruthy()
  })
})
