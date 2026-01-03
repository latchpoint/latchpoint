import { describe, expect, it } from 'vitest'

describe('MqttSettingsCard', () => {
  it('imports', async () => {
    const mod = await import('./MqttSettingsCard')
    expect(mod).toBeTruthy()
  })
})
