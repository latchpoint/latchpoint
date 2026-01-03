import { describe, expect, it } from 'vitest'

describe('SetupMqttCard', () => {
  it('imports', async () => {
    const mod = await import('./SetupMqttCard')
    expect(mod).toBeTruthy()
  })
})
