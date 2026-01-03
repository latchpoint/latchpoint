import { describe, expect, it } from 'vitest'

describe('computeSimulationDiff', () => {
  it('imports', async () => {
    const mod = await import('./computeSimulationDiff')
    expect(mod).toBeTruthy()
  })
})
