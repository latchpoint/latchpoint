import { describe, expect, it } from 'vitest'

describe('controlPanels', () => {
  it('imports', async () => {
    const mod = await import('./controlPanels')
    expect(mod).toBeTruthy()
  })
})
