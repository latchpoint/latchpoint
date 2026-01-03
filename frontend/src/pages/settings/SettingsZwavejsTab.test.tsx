import { describe, expect, it } from 'vitest'

describe('SettingsZwavejsTab', () => {
  it('imports', async () => {
    const mod = await import('./SettingsZwavejsTab')
    expect(mod).toBeTruthy()
  })
})
