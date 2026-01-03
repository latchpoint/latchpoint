import { describe, expect, it } from 'vitest'

describe('icon-button', () => {
  it('imports', async () => {
    const mod = await import('./icon-button')
    expect(mod).toBeTruthy()
  })
})
