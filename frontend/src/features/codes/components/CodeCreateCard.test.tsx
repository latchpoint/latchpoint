import { describe, expect, it } from 'vitest'

describe('CodeCreateCard', () => {
  it('imports', async () => {
    const mod = await import('./CodeCreateCard')
    expect(mod).toBeTruthy()
  })
})
