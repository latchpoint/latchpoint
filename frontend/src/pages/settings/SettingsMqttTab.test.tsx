import { describe, expect, it } from 'vitest'

describe('SettingsMqttTab', () => {
  it('imports', async () => {
    const mod = await import('./SettingsMqttTab')
    expect(mod).toBeTruthy()
  })
})
