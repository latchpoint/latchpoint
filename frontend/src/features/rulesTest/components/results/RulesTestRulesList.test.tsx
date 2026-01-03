import { describe, expect, it } from 'vitest'

describe('RulesTestRulesList', () => {
  it('imports', async () => {
    const mod = await import('./RulesTestRulesList')
    expect(mod).toBeTruthy()
  })
})
