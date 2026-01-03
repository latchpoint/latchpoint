import { describe, expect, it } from 'vitest'

describe('mqtt', () => {
  it('imports', async () => {
    const mod = await import('./mqtt')
    expect(mod).toBeTruthy()
  })
})
