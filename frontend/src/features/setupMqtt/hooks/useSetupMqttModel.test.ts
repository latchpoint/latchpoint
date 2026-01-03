import { describe, expect, it } from 'vitest'

describe('useSetupMqttModel', () => {
  it('imports', async () => {
    const mod = await import('./useSetupMqttModel')
    expect(mod).toBeTruthy()
  })
})
