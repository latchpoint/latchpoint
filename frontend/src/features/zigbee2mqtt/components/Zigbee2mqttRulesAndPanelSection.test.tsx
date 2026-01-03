import { describe, expect, it } from 'vitest'

describe('Zigbee2mqttRulesAndPanelSection', () => {
  it('imports', async () => {
    const mod = await import('./Zigbee2mqttRulesAndPanelSection')
    expect(mod).toBeTruthy()
  })
})
