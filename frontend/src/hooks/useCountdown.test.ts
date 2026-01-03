import { describe, expect, it } from 'vitest'

describe('useCountdown', () => {
  it('imports', async () => {
    const mod = await import('./useCountdown')
    expect(mod).toBeTruthy()
  })
})
