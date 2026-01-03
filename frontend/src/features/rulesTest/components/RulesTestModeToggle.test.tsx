import { describe, expect, it } from 'vitest'

describe('RulesTestModeToggle', () => {
  it('imports', async () => {
    const mod = await import('./RulesTestModeToggle')
    expect(mod).toBeTruthy()
  })
})
