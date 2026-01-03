import { describe, expect, it } from 'vitest'

describe('settings', () => {
  it('imports', async () => {
    const mod = await import('./settings')
    expect(mod).toBeTruthy()
  })
})
