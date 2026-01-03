import { describe, expect, it } from 'vitest'

describe('useQueryErrorHandler', () => {
  it('imports', async () => {
    const mod = await import('./useQueryErrorHandler')
    expect(mod).toBeTruthy()
  })
})
