import { describe, expect, it } from 'vitest'

describe('SimulationOptionsBar', () => {
  it('imports', async () => {
    const mod = await import('./SimulationOptionsBar')
    expect(mod).toBeTruthy()
  })
})
