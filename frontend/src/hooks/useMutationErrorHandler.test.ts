import { describe, expect, it } from 'vitest'

describe('useMutationErrorHandler', () => {
  it('imports', async () => {
    const mod = await import('./useMutationErrorHandler')
    expect(mod).toBeTruthy()
  })
})
