import { describe, expect, it } from 'vitest'

describe('IntegrationOverviewCard', () => {
  it('imports', async () => {
    const mod = await import('./IntegrationOverviewCard')
    expect(mod).toBeTruthy()
  })
})
