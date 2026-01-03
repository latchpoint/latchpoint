import { describe, expect, it } from 'vitest'

describe('AlarmBehaviorCard', () => {
  it('imports', async () => {
    const mod = await import('./AlarmBehaviorCard')
    expect(mod).toBeTruthy()
  })
})
