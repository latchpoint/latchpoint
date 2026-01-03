import { describe, expect, it } from 'vitest'

describe('page-header', () => {
  it('imports', async () => {
    const mod = await import('./page-header')
    expect(mod).toBeTruthy()
  })
})
