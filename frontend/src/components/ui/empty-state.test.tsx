import { describe, expect, it } from 'vitest'

describe('empty-state', () => {
  it('imports', async () => {
    const mod = await import('./empty-state')
    expect(mod).toBeTruthy()
  })
})
