import { describe, expect, it } from 'vitest'

describe('ThenBuilderCard', () => {
  it('imports', async () => {
    const mod = await import('./ThenBuilderCard')
    expect(mod).toBeTruthy()
  })
})
