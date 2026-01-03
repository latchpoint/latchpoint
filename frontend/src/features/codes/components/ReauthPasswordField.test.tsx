import { describe, expect, it } from 'vitest'

describe('ReauthPasswordField', () => {
  it('imports', async () => {
    const mod = await import('./ReauthPasswordField')
    expect(mod).toBeTruthy()
  })
})
