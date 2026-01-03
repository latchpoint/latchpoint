import { describe, expect, it } from 'vitest'

describe('HomeAssistantOverviewCard', () => {
  it('imports', async () => {
    const mod = await import('./HomeAssistantOverviewCard')
    expect(mod).toBeTruthy()
  })
})
