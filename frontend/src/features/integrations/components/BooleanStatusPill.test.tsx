import { describe, expect, it } from 'vitest'

describe('BooleanStatusPill', () => {
  it('imports', async () => {
    const mod = await import('./BooleanStatusPill')
    expect(mod).toBeTruthy()
  })
})
