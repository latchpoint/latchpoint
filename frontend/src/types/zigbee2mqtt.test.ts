import { describe, expect, it } from 'vitest'

describe('zigbee2mqtt', () => {
  it('imports', async () => {
    const mod = await import('./zigbee2mqtt')
    expect(mod).toBeTruthy()
  })
})
