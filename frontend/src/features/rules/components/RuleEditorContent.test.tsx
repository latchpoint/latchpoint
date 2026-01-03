import { describe, expect, it } from 'vitest'

describe('RuleEditorContent', () => {
  it('imports', async () => {
    const mod = await import('./RuleEditorContent')
    expect(mod).toBeTruthy()
  })
})
