import { describe, expect, it } from 'vitest'

describe('AlarmHistory', () => {
  it('imports', async () => {
    const mod = await import('./AlarmHistory')
    expect(mod).toBeTruthy()
  })
})
