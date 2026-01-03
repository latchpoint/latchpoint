import { describe, expect, it } from 'vitest'

describe('Zigbee2mqttEnableSection', () => {
  it('imports', async () => {
    const mod = await import('./Zigbee2mqttEnableSection')
    expect(mod).toBeTruthy()
  })
})
