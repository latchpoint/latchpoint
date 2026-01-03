import { describe, expect, it } from 'vitest'

describe('EventRow', () => {
  it('imports', async () => {
    const mod = await import('./EventRow')
    expect(mod).toBeTruthy()
  })
})
