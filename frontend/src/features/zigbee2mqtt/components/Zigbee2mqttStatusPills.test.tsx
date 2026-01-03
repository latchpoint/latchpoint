import { describe, expect, it } from 'vitest'

describe('Zigbee2mqttStatusPills', () => {
  it('imports', async () => {
    const mod = await import('./Zigbee2mqttStatusPills')
    expect(mod).toBeTruthy()
  })
})
