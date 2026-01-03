import { describe, expect, it } from 'vitest'

describe('errorHandler', () => {
  it('imports', async () => {
    const mod = await import('./errorHandler')
    expect(mod).toBeTruthy()
  })
})
