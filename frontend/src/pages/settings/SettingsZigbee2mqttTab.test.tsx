import { describe, expect, it } from 'vitest'

describe('SettingsZigbee2mqttTab', () => {
  it('imports', async () => {
    const mod = await import('./SettingsZigbee2mqttTab')
    expect(mod).toBeTruthy()
  })
})
