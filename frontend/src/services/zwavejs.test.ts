import { describe, expect, it } from 'vitest'

describe('zwavejs', () => {
  it('imports', async () => {
    const mod = await import('./zwavejs')
    expect(mod).toBeTruthy()
  })
})
