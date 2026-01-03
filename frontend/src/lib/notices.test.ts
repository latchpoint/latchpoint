import { describe, expect, it } from 'vitest'

describe('notices', () => {
  it('imports', async () => {
    const mod = await import('./notices')
    expect(mod).toBeTruthy()
  })
})
