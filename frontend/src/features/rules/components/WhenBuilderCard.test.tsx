import { describe, expect, it } from 'vitest'

describe('WhenBuilderCard', () => {
  it('imports', async () => {
    const mod = await import('./WhenBuilderCard')
    expect(mod).toBeTruthy()
  })
})
