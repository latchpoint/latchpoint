import { describe, expect, it } from 'vitest'

describe('load-more', () => {
  it('imports', async () => {
    const mod = await import('./load-more')
    expect(mod).toBeTruthy()
  })
})
