import { describe, expect, it } from 'vitest'

describe('useHomeAssistantMqttAlarmEntity', () => {
  it('imports', async () => {
    const mod = await import('./useHomeAssistantMqttAlarmEntity')
    expect(mod).toBeTruthy()
  })
})
