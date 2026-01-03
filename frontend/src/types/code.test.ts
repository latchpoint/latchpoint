import { describe, expect, it } from 'vitest'

describe('code', () => {
  it('imports', async () => {
    const mod = await import('./code')
    expect(mod).toBeTruthy()
  })
})
