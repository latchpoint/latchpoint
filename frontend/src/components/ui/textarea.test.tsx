import { describe, expect, it } from 'vitest'

describe('textarea', () => {
  it('imports', async () => {
    const mod = await import('./textarea')
    expect(mod).toBeTruthy()
  })
})
