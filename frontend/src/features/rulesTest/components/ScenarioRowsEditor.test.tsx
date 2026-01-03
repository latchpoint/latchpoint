import { describe, expect, it } from 'vitest'

describe('ScenarioRowsEditor', () => {
  it('imports', async () => {
    const mod = await import('./ScenarioRowsEditor')
    expect(mod).toBeTruthy()
  })
})
