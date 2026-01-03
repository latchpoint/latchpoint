import { describe, expect, it } from 'vitest'

describe('onboarding', () => {
  it('imports', async () => {
    const mod = await import('./onboarding')
    expect(mod).toBeTruthy()
  })
})
