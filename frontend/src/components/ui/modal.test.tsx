import { describe, expect, it } from 'vitest'

describe('modal', () => {
  it('imports', async () => {
    const mod = await import('./modal')
    expect(mod).toBeTruthy()
  })
})
