import { describe, expect, it } from 'vitest'

describe('ruleDefinition', () => {
  it('imports', async () => {
    const mod = await import('./ruleDefinition')
    expect(mod).toBeTruthy()
  })
})
