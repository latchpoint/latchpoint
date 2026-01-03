import { describe, expect, it } from 'vitest'

describe('validation', () => {
  it('imports', async () => {
    const mod = await import('./validation')
    expect(mod).toBeTruthy()
  })
})
