import { describe, expect, it } from 'vitest'

describe('alert', () => {
  it('imports', async () => {
    const mod = await import('./alert')
    expect(mod).toBeTruthy()
  })
})
