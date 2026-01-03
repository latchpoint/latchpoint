import { describe, expect, it } from 'vitest'

describe('Zigbee2mqttSettingsCard', () => {
  it('imports', async () => {
    const mod = await import('./Zigbee2mqttSettingsCard')
    expect(mod).toBeTruthy()
  })
})
