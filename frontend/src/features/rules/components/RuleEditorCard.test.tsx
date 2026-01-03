import { describe, expect, it } from 'vitest'

describe('RuleEditorCard', () => {
  it('imports', async () => {
    const mod = await import('./RuleEditorCard')
    expect(mod).toBeTruthy()
  })
})
