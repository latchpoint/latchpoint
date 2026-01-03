import { describe, expect, it } from 'vitest'

describe('SetupZwavejsCard', () => {
  it('imports', async () => {
    const mod = await import('./SetupZwavejsCard')
    expect(mod).toBeTruthy()
  })
})
