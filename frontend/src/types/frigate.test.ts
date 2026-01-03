import { describe, expect, it } from 'vitest'

describe('frigate', () => {
  it('imports', async () => {
    const mod = await import('./frigate')
    expect(mod).toBeTruthy()
  })
})
