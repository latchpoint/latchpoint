import { describe, expect, it } from 'vitest'

describe('help-tip', () => {
  it('imports', async () => {
    const mod = await import('./help-tip')
    expect(mod).toBeTruthy()
  })
})
