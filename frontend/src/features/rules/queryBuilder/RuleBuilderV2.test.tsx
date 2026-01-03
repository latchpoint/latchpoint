import { describe, expect, it } from 'vitest'

describe('RuleBuilderV2', () => {
  it('imports', async () => {
    const mod = await import('./RuleBuilderV2')
    expect(mod).toBeTruthy()
  })
})
