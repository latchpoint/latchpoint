import { describe, expect, it } from 'vitest'

describe('App', () => {
  it('imports', async () => {
    const mod = await import('./App')
    expect(mod).toBeTruthy()
  })
})
