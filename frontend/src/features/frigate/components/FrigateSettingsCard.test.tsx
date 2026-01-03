import { describe, expect, it } from 'vitest'

describe('FrigateSettingsCard', () => {
  it('imports', async () => {
    const mod = await import('./FrigateSettingsCard')
    expect(mod).toBeTruthy()
  })
})
