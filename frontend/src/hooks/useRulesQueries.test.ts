import { describe, expect, it } from 'vitest'

describe('useRulesQueries', () => {
  it('imports', async () => {
    const mod = await import('./useRulesQueries')
    expect(mod).toBeTruthy()
  })
})
