import { describe, expect, it } from 'vitest'

describe('IntegrationConnectionCard', () => {
  it('imports', async () => {
    const mod = await import('./IntegrationConnectionCard')
    expect(mod).toBeTruthy()
  })
})
