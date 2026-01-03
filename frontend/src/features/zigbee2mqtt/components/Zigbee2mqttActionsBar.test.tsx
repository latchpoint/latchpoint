import { describe, expect, it } from 'vitest'

describe('Zigbee2mqttActionsBar', () => {
  it('imports', async () => {
    const mod = await import('./Zigbee2mqttActionsBar')
    expect(mod).toBeTruthy()
  })
})
