import { describe, expect, it } from 'vitest'

describe('useZigbee2mqtt', () => {
  it('imports', async () => {
    const mod = await import('./useZigbee2mqtt')
    expect(mod).toBeTruthy()
  })
})
