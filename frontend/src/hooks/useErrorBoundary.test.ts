import { describe, expect, it } from 'vitest'

describe('useErrorBoundary', () => {
  it('imports', async () => {
    const mod = await import('./useErrorBoundary')
    expect(mod).toBeTruthy()
  })
})
