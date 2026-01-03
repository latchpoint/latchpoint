import { describe, expect, it } from 'vitest'

describe('badge-variants', () => {
  it('imports', async () => {
    const mod = await import('./badge-variants')
    expect(mod).toBeTruthy()
  })
})
