import { describe, expect, it } from 'vitest'

describe('AlarmStateValueEditor', () => {
  it('imports', async () => {
    const mod = await import('./AlarmStateValueEditor')
    expect(mod).toBeTruthy()
  })
})
