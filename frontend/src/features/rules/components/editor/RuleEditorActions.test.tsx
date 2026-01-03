import { describe, expect, it } from 'vitest'

describe('RuleEditorActions', () => {
  it('imports', async () => {
    const mod = await import('./RuleEditorActions')
    expect(mod).toBeTruthy()
  })
})
