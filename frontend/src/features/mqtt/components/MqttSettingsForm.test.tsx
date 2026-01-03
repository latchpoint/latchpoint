import { describe, expect, it } from 'vitest'

describe('MqttSettingsForm', () => {
  it('imports', async () => {
    const mod = await import('./MqttSettingsForm')
    expect(mod).toBeTruthy()
  })
})
