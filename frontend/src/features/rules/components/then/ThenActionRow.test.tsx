import { describe, expect, it } from 'vitest'

describe('ThenActionRow', () => {
  it('imports', async () => {
    const mod = await import('./ThenActionRow')
    expect(mod).toBeTruthy()
  })
})
