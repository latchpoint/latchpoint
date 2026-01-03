import { describe, expect, it } from 'vitest'

describe('builder', () => {
  it('imports', async () => {
    const mod = await import('./builder')
    expect(mod).toBeTruthy()
  })
})
