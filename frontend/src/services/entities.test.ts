import { describe, expect, it } from 'vitest'

describe('entities', () => {
  it('imports', async () => {
    const mod = await import('./entities')
    expect(mod).toBeTruthy()
  })
})
