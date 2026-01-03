import { describe, expect, it } from 'vitest'

describe('constants', () => {
  it('imports', async () => {
    const mod = await import('./constants')
    expect(mod).toBeTruthy()
  })
})
