import { describe, expect, it } from 'vitest'

describe('select', () => {
  it('imports', async () => {
    const mod = await import('./select')
    expect(mod).toBeTruthy()
  })
})
