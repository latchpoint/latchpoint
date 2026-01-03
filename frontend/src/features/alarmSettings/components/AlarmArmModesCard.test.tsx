import { describe, expect, it } from 'vitest'

describe('AlarmArmModesCard', () => {
  it('imports', async () => {
    const mod = await import('./AlarmArmModesCard')
    expect(mod).toBeTruthy()
  })
})
