import { describe, expect, it } from 'vitest'

describe('AlarmPanel', () => {
  it('imports', async () => {
    const mod = await import('./AlarmPanel')
    expect(mod).toBeTruthy()
  })
})
