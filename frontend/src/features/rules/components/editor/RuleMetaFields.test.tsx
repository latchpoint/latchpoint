import { describe, expect, it } from 'vitest'

describe('RuleMetaFields', () => {
  it('imports', async () => {
    const mod = await import('./RuleMetaFields')
    expect(mod).toBeTruthy()
  })
})
