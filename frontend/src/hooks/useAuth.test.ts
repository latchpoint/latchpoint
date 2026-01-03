import { describe, expect, it } from 'vitest'

describe('useAuth', () => {
  it('imports', async () => {
    const mod = await import('./useAuth')
    expect(mod).toBeTruthy()
  })
})
