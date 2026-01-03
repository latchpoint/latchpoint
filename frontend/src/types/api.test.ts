import { describe, expect, it } from 'vitest'

describe('api', () => {
  it('imports', async () => {
    const mod = await import('./api')
    expect(mod).toBeTruthy()
  })
})
