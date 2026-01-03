import { describe, expect, it } from 'vitest'

describe('ProtectedRoute', () => {
  it('imports', async () => {
    const mod = await import('./ProtectedRoute')
    expect(mod).toBeTruthy()
  })
})
