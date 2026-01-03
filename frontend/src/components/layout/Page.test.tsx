import { describe, expect, it } from 'vitest'

describe('Page', () => {
  it('imports', async () => {
    const mod = await import('./Page')
    expect(mod).toBeTruthy()
  })
})
