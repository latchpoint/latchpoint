import { describe, expect, it } from 'vitest'

describe('RuleQueryBuilder', () => {
  it('imports', async () => {
    const mod = await import('./RuleQueryBuilder')
    expect(mod).toBeTruthy()
  })
})
