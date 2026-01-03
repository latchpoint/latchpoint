import { describe, expect, it } from 'vitest'

describe('HomeAssistantConnectionCard', () => {
  it('imports', async () => {
    const mod = await import('./HomeAssistantConnectionCard')
    expect(mod).toBeTruthy()
  })
})
