import { describe, expect, it } from 'vitest'

describe('HomeAssistantMqttAlarmEntityCard', () => {
  it('imports', async () => {
    const mod = await import('./HomeAssistantMqttAlarmEntityCard')
    expect(mod).toBeTruthy()
  })
})
