import { describe, expect, it } from 'vitest'

describe('RulesPageActions', () => {
  it('imports', async () => {
    const mod = await import('./RulesPageActions')
    expect(mod).toBeTruthy()
  })
})
