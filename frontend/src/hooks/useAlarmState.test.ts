import { describe, expect, it } from 'vitest'

describe('useAlarmState', () => {
  it('imports', async () => {
    const mod = await import('./useAlarmState')
    expect(mod).toBeTruthy()
  })
})
