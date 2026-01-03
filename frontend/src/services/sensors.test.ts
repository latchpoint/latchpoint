import { describe, expect, it } from 'vitest'

describe('sensors', () => {
  it('imports', async () => {
    const mod = await import('./sensors')
    expect(mod).toBeTruthy()
  })
})
