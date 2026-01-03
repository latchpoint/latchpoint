import { describe, expect, it } from 'vitest'

describe('useAlarm', () => {
  it('imports', async () => {
    const mod = await import('./useAlarm')
    expect(mod).toBeTruthy()
  })
})
