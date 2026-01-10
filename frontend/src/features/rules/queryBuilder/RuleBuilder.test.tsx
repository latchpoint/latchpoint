import { describe, expect, it } from 'vitest'

describe('RuleBuilder', () => {
  it('imports', async () => {
    const mod = await import('./RuleBuilder')
    expect(mod).toBeTruthy()
  })
})
