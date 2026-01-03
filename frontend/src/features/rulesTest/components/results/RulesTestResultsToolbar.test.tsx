import { describe, expect, it } from 'vitest'

describe('RulesTestResultsToolbar', () => {
  it('imports', async () => {
    const mod = await import('./RulesTestResultsToolbar')
    expect(mod).toBeTruthy()
  })
})
