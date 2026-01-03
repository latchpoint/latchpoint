import { describe, expect, it } from 'vitest'

describe('RulesBuilderPageActions', () => {
  it('imports', async () => {
    const mod = await import('./RulesBuilderPageActions')
    expect(mod).toBeTruthy()
  })
})
