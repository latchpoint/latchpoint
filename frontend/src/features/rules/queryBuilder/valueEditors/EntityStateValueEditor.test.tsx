import { describe, expect, it } from 'vitest'

describe('EntityStateValueEditor', () => {
  it('imports', async () => {
    const mod = await import('./EntityStateValueEditor')
    expect(mod).toBeTruthy()
  })
})
