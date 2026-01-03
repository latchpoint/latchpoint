import { describe, expect, it } from 'vitest'

describe('RuleDefinitionEditor', () => {
  it('imports', async () => {
    const mod = await import('./RuleDefinitionEditor')
    expect(mod).toBeTruthy()
  })
})
