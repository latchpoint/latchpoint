import { describe, expect, it } from 'vitest'

describe('numberParsers', () => {
  it('imports', async () => {
    const mod = await import('./numberParsers')
    expect(mod).toBeTruthy()
  })
})
