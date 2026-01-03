import { describe, expect, it } from 'vitest'

describe('AlarmArmActionFields', () => {
  it('imports', async () => {
    const mod = await import('./AlarmArmActionFields')
    expect(mod).toBeTruthy()
  })
})
