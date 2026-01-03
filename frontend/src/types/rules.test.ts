import { describe, expect, it } from 'vitest'

describe('rules', () => {
  it('imports', async () => {
    const mod = await import('./rules')
    expect(mod).toBeTruthy()
  })
})
