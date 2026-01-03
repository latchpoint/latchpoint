import { describe, expect, it } from 'vitest'

describe('AppErrorBoundary', () => {
  it('imports', async () => {
    const mod = await import('./AppErrorBoundary')
    expect(mod).toBeTruthy()
  })
})
