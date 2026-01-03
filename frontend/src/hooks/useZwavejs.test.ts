import { describe, expect, it } from 'vitest'

describe('useZwavejs', () => {
  it('imports', async () => {
    const mod = await import('./useZwavejs')
    expect(mod).toBeTruthy()
  })
})
