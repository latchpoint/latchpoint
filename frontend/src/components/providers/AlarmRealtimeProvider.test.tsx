import { describe, expect, it } from 'vitest'

describe('AlarmRealtimeProvider', () => {
  it('imports', async () => {
    const mod = await import('./AlarmRealtimeProvider')
    expect(mod).toBeTruthy()
  })
})
