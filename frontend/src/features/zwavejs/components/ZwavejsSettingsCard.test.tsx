import { describe, expect, it } from 'vitest'

describe('ZwavejsSettingsCard', () => {
  it('imports', async () => {
    const mod = await import('./ZwavejsSettingsCard')
    expect(mod).toBeTruthy()
  })
})
