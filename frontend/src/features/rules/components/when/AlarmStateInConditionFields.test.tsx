import { describe, expect, it } from 'vitest'

describe('AlarmStateInConditionFields', () => {
  it('imports', async () => {
    const mod = await import('./AlarmStateInConditionFields')
    expect(mod).toBeTruthy()
  })
})
