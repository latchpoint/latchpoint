import { describe, expect, it } from 'vitest'

describe('useMqtt', () => {
  it('imports', async () => {
    const mod = await import('./useMqtt')
    expect(mod).toBeTruthy()
  })
})
